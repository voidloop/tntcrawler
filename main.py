import time

from crawler import TntCrawler, TntWriter, TntEntry
from clutch.core import Client
from queue import Queue, Empty
from tkinter import ttk
import asyncio
import requests.exceptions
import tkinter as tk
import threading




class StatusBar(tk.Frame):
    def __init__(self, master):
        super().__init__(master, relief=tk.SUNKEN)
        self.variable = tk.StringVar()
        self.disconnected_image = tk.BitmapImage(file='images/disconnected.xbm')
        self.connected_image = tk.BitmapImage(file='images/connected.xbm')

        self.columnconfigure(0, weight=1)
        self.label = tk.Label(self, bd=1, anchor=tk.W, textvariable=self.variable)
        self.label.grid(row=0, column=0, sticky='WE')

        self.connection_status = tk.Label(self, image=self.disconnected_image)
        self.connection_status.grid(row=0, column=1)

        self.pack(side=tk.BOTTOM, fill=tk.X)

    def connected(self):
        self.connection_status['image'] = self.connected_image

    def disconnected(self):
        self.connection_status['image'] = self.disconnected_image

    def text(self, text):
        self.variable.set(text)


class InputFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.columnconfigure(1, weight=1)
        self.label = tk.Label(self, text='Keyword:')
        self.label.grid(row=0, column=0, sticky=tk.E, padx=3)
        self.keyword = tk.Entry(self)
        self.keyword.grid(row=0, column=1, sticky='WE', padx=3)
        self.search = tk.Button(self, text='Search')
        self.search.grid(row=0, column=2, sticky=tk.W, padx=3)

        self.pack(side=tk.TOP, fill=tk.X)

    def disabled(self):
        self.search['state'] = tk.DISABLED
        self.keyword['state'] = tk.DISABLED

    def enabled(self):
        self.search['state'] = tk.NORMAL
        self.keyword['state'] = tk.NORMAL

    def get_keyword(self):
        return self.keyword.get()

    def command(self, command):
        self.search['command'] = command
        self.keyword.bind('<Return>', command)


class OutputFrame(tk.Frame):
    columns = ('seeders', 'leeches', 'downloaded', 'title')

    def __init__(self, master):
        super().__init__(master)
        self.scrollbar = ttk.Scrollbar(self)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.treeview = ttk.Treeview(master=self, show='headings', columns=self.columns,
                                     yscrollcommand=self.scrollbar.set)
        self.scrollbar.config(command=self.treeview.yview)

        self.menu = None
        self.treeview.bind('<Button-3>', self._popup)

        self.treeview.heading('title', text='Title',
                              command=lambda: self._sort_column('title'))
        self.treeview.heading('seeders', text='Seeders',
                              command=lambda: self._sort_column('seeders', klass=int))
        self.treeview.heading('leeches', text='Leeches',
                              command=lambda: self._sort_column('leeches', klass=int))
        self.treeview.heading('downloaded', text='Downloaded',
                              command=lambda: self._sort_column('downloaded', klass=int))
        self.treeview.pack(expand=tk.YES, fill=tk.BOTH)
        self.pack(expand=tk.YES, fill=tk.BOTH)
        self._magnets = []

    def set_menu(self, menu):
        self.menu = menu

    def _popup(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        except AttributeError:
            pass

    def _sort_column(self, column, reverse=False, klass: type = str):
        items = [(self.treeview.set(k, column), k) for k in self.treeview.get_children('')]
        items.sort(reverse=reverse, key=lambda item: klass(item[0]))

        # rearrange items in sorted positions
        for index, (val, k) in enumerate(items):
            self.treeview.move(k, '', index)

        # reverse sort next time
        self.treeview.heading(column, command=lambda: self._sort_column(column, not reverse, klass))

    def clear(self):
        self.treeview.delete(*self.treeview.get_children())
        self._magnets.clear()

    def selection(self):
        return self.treeview.selection()

    def _values_of(self, tnt_entry: TntEntry):
        return [tnt_entry._asdict()[column] for column in self.columns]

    def add(self, tnt_entry: TntEntry):
        item = self.treeview.insert('', 'end', values=self._values_of(tnt_entry))
        self._magnets.append(tnt_entry.magnet)


class TntCrawlerThread(threading.Thread):
    def __init__(self, keyword):
        super().__init__()
        self.queue = Queue()
        self._keyword = keyword
        self._lock = threading.Lock()
        self.daemon = True

    def run(self):
        class TntQueueWriter(TntWriter):
            def __init__(self, queue: Queue):
                super().__init__()
                self._queue = queue

            def add(self, tnt_entry: TntEntry):
                self._queue.put(tnt_entry)

        loop = asyncio.new_event_loop()
        crawler = TntCrawler(loop, TntQueueWriter(self.queue))
        crawler.setup(self._keyword, 0)
        loop.run_until_complete(crawler.crawl())
        crawler.shutdown()
        loop.close()
        self.queue.put(None)

    def stop(self):
        with self._lock:
            if self._loop:
                self._loop.call_soon_threadsafe(self._crawler.stop)


class Application(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self._loop = asyncio.new_event_loop()
        self.client = Client()
        self.magnets = dict()
        self.status_bar = StatusBar(self)
        self.control_frame = InputFrame(self)
        self.output_frame = OutputFrame(self)

        self.output_menu = tk.Menu(self.output_frame, tearoff=0)
        self.output_menu.add_command(label='Download selected', command=self._download_selection())
        self.output_frame.set_menu(self.output_menu)

        self.control_frame.command(self._start_crawler_thread)
        self.pack(expand=tk.YES, fill=tk.BOTH)
        self.status_bar.text('Welcome!')

        self._stop_event = threading.Event()
        self._check_thread = threading.Thread(target=self._check_transmission_connection)
        # self._check_thread.start()
        self._crawler_thread = None

    def shutdown(self):
        self._crawler_thread.join()

    def _check_transmission_connection(self):
        while not self._stop_event.is_set():
            try:
                self.client.list()
                self.status_bar.connected()
            except requests.exceptions.ConnectionError:
                self.status_bar.disconnected()
            time.sleep(1)

    def _download_selection(self):
        items = self.output_frame.selection()
        for item in items:
            try:
                self.client.torrent.add(filename=self.magnets[item])
            except requests.exceptions.ConnectionError:
                self.status_bar.disconnected()

    def _start_crawler_thread(self, *args):
        if self._crawler_thread is None:
            self._crawler_thread = TntCrawlerThread(keyword=self.control_frame.keyword.get())
            self.output_frame.clear()
            self.magnets.clear()
            self._crawler_thread.start()
            self.master.after(1000, self._process_queue, self._crawler_thread.queue)
            self._start_downloading()

    def _process_queue(self, queue):
        try:
            while True:
                tnt_entry = queue.get(False)
                if tnt_entry is None:
                    self._download_finished()
                    break
                self.output_frame.add(tnt_entry)
                queue.task_done()
        except Empty:
            self.master.after(100, self._process_queue, queue)

    def _start_downloading(self):
        self.control_frame.disabled()
        self.status_bar.text('Downloading...')

    def _download_finished(self):
        self.control_frame.enabled()
        length = len(self.output_frame._magnets)
        text = 'entries'
        if length == 1:
            text = 'entry'
        self.status_bar.text('Downloaded {} {}'.format(length, text))


def main():
    root = tk.Tk()
    root.wm_title('TNT Crawler')
    app = Application(master=root)

    def destroy():
        app.shutdown()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', destroy)
    app.mainloop()


if __name__ == '__main__':
    main()
