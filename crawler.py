from bs4 import BeautifulSoup
from collections import namedtuple
import aiohttp
import asyncio


TntEntry = namedtuple('TntEntry', 'torrent magnet title leeches seeders downloaded')


class TntWriter:
    def entry_parsed(self, tnt_entry: TntEntry):
        pass

    def before_first_page(self):
        pass

    def after_first_page(self, num_pages):
        pass

    def before_page(self, page):
        pass

    def after_page(self, page):
        pass

    def page_processed(self, page):
        pass


class TntCrawlerError(Exception):
    pass


class CancelOnEvent:
    def __init__(self, event, future, loop):
        self._future = future
        self._event = event
        self._loop = loop

    async def __aenter__(self):
        self._cancel_task = asyncio.ensure_future(self._cancellation_task(), loop=self._loop)

    async def __aexit__(self, *exc):
        try:
            self._cancel_task.cancel()
            await self._cancel_task
        except asyncio.CancelledError:
            pass

    async def _cancellation_task(self):
        await self._event.wait()
        self._future.cancel()


class TntCrawler:
    release_list = 'http://www.tntvillage.scambioetico.org/src/releaselist.php'

    def __init__(self, loop, writer: TntWriter, max_workers=10):
        self._loop: asyncio.AbstractEventLoop = loop
        self._semaphore = asyncio.BoundedSemaphore(max_workers, loop=loop)
        self._stop_event = asyncio.Event(loop=loop)
        self._writer = writer
        self._keyword = ''
        self._category = 0

    def setup(self, keyword, category):
        if keyword is None:
            raise TntCrawlerError('you must specify a valid keyword')
        if category is None:
            raise TntCrawlerError('you must specify a valid category')
        self._keyword = keyword
        self._category = category

    async def crawl(self):
        session = aiohttp.ClientSession(loop=self._loop)
        await self._crawler_task(session)
        await session.close()

    async def _crawler_task(self, session):
        self._stop_event.clear()

        task = asyncio.ensure_future(self._fetch(1, session), loop=self._loop)
        async with CancelOnEvent(self._stop_event, task, self._loop):
            try:
                self._writer.before_first_page()
                first_page = await task
                num_pages = self.get_num_pages(first_page)
                self._writer.after_first_page(num_pages)
            except asyncio.CancelledError:
                print('first page downloading stopped')
                return

        self._write_tnt_entries(first_page)
        print(f'page 1 processed, ', end='')
        self._writer.page_processed(1)

        if num_pages > 1:
            print(f'other {num_pages-1} pages to download')
        else:
            print('no other pages to download')
            return

        workers = []
        for page in range(2, num_pages+1):

            acquire_semaphore = asyncio.ensure_future(self._semaphore.acquire(), loop=self._loop)
            async with CancelOnEvent(self._stop_event, acquire_semaphore, self._loop):
                try:
                    await acquire_semaphore
                except asyncio.CancelledError:
                    print('spawning loop stopped')
                    break

            workers.append(asyncio.ensure_future(self._work(page, session), loop=self._loop))

        group = asyncio.gather(*workers, loop=self._loop)
        async with CancelOnEvent(self._stop_event, group, self._loop):
            try:
                await group
            except asyncio.CancelledError:
                print('running workers stopped')

    def stop(self):
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop_event.set)

    async def _work(self, page, session):
        try:
            self._writer.before_page(page)
            html = await self._fetch(page, session)
            self._writer.after_page(page)
            self._write_tnt_entries(html)
            print(f'page {page} processed')
            self._writer.page_processed(page)
        finally:
            self._semaphore.release()

    async def _fetch(self, page, session):
        data = {'srcrel': self._keyword, 'cat': self._category, 'page': page}
        print(f'downloading page {page}...')
        async with session.post(self.release_list, data=data) as response:
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
        try:
            for row in table[0].find_all('tr')[1:]:
                tnt_entry = self._create_tnt_entry(row)
                self._writer.entry_parsed(tnt_entry)
        except IndexError:
            print('failed a row parsing')

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
        def entry_parsed(self, tnt_entry: TntEntry):
            print(tnt_entry.magnet)

    event_loop = asyncio.get_event_loop()
    crawler = TntCrawler(event_loop, TntStdoutWriter())
    crawler.setup('ciao', 0)
    event_loop.run_until_complete(crawler.crawl())
    event_loop.close()
