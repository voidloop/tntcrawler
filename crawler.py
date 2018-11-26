from abc import abstractmethod, ABC
from bs4 import BeautifulSoup
from collections import namedtuple
import aiohttp
import asyncio


class TntWriter(ABC):
    @abstractmethod
    def add(self, magnet):
        pass


TntEntry = namedtuple('TntEntry', 'torrent magnet title leeches seeders downloaded')


class TntCrawlerError(Exception):
    pass


class TntCrawler:
    release_list = 'http://www.tntvillage.scambioetico.org/src/releaselist.php'

    def __init__(self, loop: asyncio.AbstractEventLoop, writer, max_workers=10):
        self._loop = loop
        self._session = aiohttp.ClientSession(loop=loop)
        self._semaphore = asyncio.BoundedSemaphore(max_workers, loop=loop)
        self._stop_event = asyncio.Event(loop=loop)
        self._writer = writer
        self._keyword = ''
        self._category = 0
        self._workers = []

    def setup(self, keyword, category):
        if keyword is None:
            raise TntCrawlerError('you must specify a valid keyword')
        if category is None:
            raise TntCrawlerError('you must specify a valid category')
        self._keyword = keyword
        self._category = category

    async def crawl(self):
        self._stop_event.clear()
        first_page = await self._fetch(1)
        self._write_tnt_entries(first_page)
        num_pages = self.get_num_pages(first_page)

        print(f'page 1 processed, ', end='')

        if num_pages > 1:
            print(f'other {num_pages-1} pages to download')
        else:
            print('no other pages to download')

        self._workers.clear()
        for page in range(2, num_pages + 1):
            await self._semaphore.acquire()
            if self._stop_event.is_set():
                break
            self._workers.append(asyncio.ensure_future(self.work(page), loop=self._loop))

        await asyncio.gather(*self._workers, loop=self._loop)

    async def work(self, page):
        try:
            html = await self._fetch(page)
            self._write_tnt_entries(html)
            print(f'page {page} processed')
        finally:
            self._semaphore.release()

    def stop(self):
        self._stop_event.set()
        [task.cancel() for task in self._workers]

    def shutdown(self):
        self._loop.run_until_complete(self._session.close())

    async def _fetch(self, page):
        data = {'srcrel': self._keyword, 'cat': self._category, 'page': page}
        print(f'downloading page {page}...')
        async with self._session.post(self.release_list, data=data) as response:
            return await response.text()

    @staticmethod
    def _create_tnt_entry(row):
        cells = row.find_all('td')
        return TntEntry(
            torrent=cells[0].find('a')['href'],
            magnet=cells[1].find('a')['href'],
            title=cells[6].find('a').string,
            seeders=int(cells[4].string),
            leeches=int(cells[3].string),
            downloaded=int(cells[5].string),
        )

    def _write_tnt_entries(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.select('.showrelease_tb > table:nth-of-type(1)')
        # headers in first row of the table
        for row in table[0].find_all('tr')[1:]:
            tnt_entry = self._create_tnt_entry(row)
            self._writer.add(tnt_entry)

    @staticmethod
    def get_num_pages(html_doc):
        soup = BeautifulSoup(html_doc, 'html.parser')
        list_items = soup.select('div[class="pagination"] > ul > li')
        for item in list_items:
            if item.text.lower() == 'ultima':
                return int(item.get('p'))
        else:
            return 0


if __name__ == '__main__':

    class TntStdoutWriter(TntWriter):
        def add(self, tnt_entry: TntEntry):
            print(tnt_entry.magnet)

    loop = asyncio.get_event_loop()
    crawler = TntCrawler(loop, TntStdoutWriter())
    crawler.setup('ciao', 0)
    try:
        loop.run_until_complete(crawler.crawl())
    finally:
        crawler.stop()
        crawler.shutdown()
    loop.close()
