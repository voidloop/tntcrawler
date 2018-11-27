from contextlib import suppress

from crawler import TntCrawler, TntWriter, TntEntry
from clutch.core import Client
from queue import Queue, Empty
from tkinter import ttk
import asyncio
import tkinter as tk
import threading


# class OutputFrame(tk.Frame):
#     columns = ('seeders', 'leeches', 'downloaded', 'title')
#
#     def __init__(self, master):
#         super().__init__(master)
#         self.scrollbar = ttk.Scrollbar(self)
#         self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
#         self.treeview = ttk.Treeview(master=self, show='headings', columns=self.columns,
#                                      yscrollcommand=self.scrollbar.set)
#         self.scrollbar.config(command=self.treeview.yview)
#
#         self.menu = None
#         self.treeview.bind('<Button-3>', self._popup)
#         self.treeview.heading('title', text='Title',
#                               command=lambda: self._sort_column('title'))
#         self.treeview.heading('seeders', text='Seeders',
#                               command=lambda: self._sort_column('seeders', klass=int))
#         self.treeview.heading('leeches', text='Leeches',
#                               command=lambda: self._sort_column('leeches', klass=int))
#         self.treeview.heading('downloaded', text='Downloaded',
#                               command=lambda: self._sort_column('downloaded', klass=int))
#         self.treeview.pack(expand=tk.YES, fill=tk.BOTH)
#         self.pack(expand=tk.YES, fill=tk.BOTH)
#         self._magnets = []
#
# def set_menu(self, menu):
#     self.menu = menu
#
# def _popup(self, event):
#     try:
#         self.menu.tk_popup(event.x_root, event.y_root)
#     except AttributeError:
#         pass
#
# def _sort_column(self, column, reverse=False, klass: type = str):
#     items = [(self.treeview.set(k, column), k) for k in self.treeview.get_children('')]
#     items.sort(reverse=reverse, key=lambda item: klass(item[0]))
#
#     # rearrange items in sorted positions
#     for index, (val, k) in enumerate(items):
#         self.treeview.move(k, '', index)
#
#     # reverse sort next time
#     self.treeview.heading(column, command=lambda: self._sort_column(column, not reverse, klass))
#
# def clear(self):
#     self.treeview.delete(*self.treeview.get_children())
#     self._magnets.clear()
#
# def selection(self):
#     return self.treeview.selection()
#

class CrawlerTask:

    class TntQueueWriter(TntWriter):
        def __init__(self, queue: Queue):
            super().__init__()
            self._queue = queue

        def add(self, tnt_entry: TntEntry):
            self._queue.put(tnt_entry)

    def __init__(self):
        self.queue = Queue()
        self._crawler = None
        self._lock = threading.Lock()
        self._loop = None

    def start(self, keyword):
        with self._lock:
            if self._crawler is None:
                threading.Thread(target=self._task, args=(keyword,)).start()

    def _task(self, keyword):
        with self._lock:
            self._loop = asyncio.new_event_loop()
            self._crawler = TntCrawler(self._loop, CrawlerTask.TntQueueWriter(self.queue))
        self._crawler.setup(keyword, 0)
        with suppress(asyncio.CancelledError):
            self._loop.run_until_complete(self._crawler.crawl())
        self._crawler.shutdown()
        self._loop.close()
        self.queue.put(None)
        with self._lock:
            self._crawler = None

    def stop(self):
        with self._lock:
            if self._crawler is None:
                return
        self._loop.call_soon_threadsafe(self._crawler.stop)


class TntTreeview(ttk.Treeview):

    columns = ('seeders', 'leeches', 'downloaded', 'title')

    def __init__(self, master):
        super().__init__(master, show='headings', columns=self.columns)

        # self.treeview.bind('<Button-3>', self._popup)

        self.heading('title', text='Title', command=lambda: self._sort_column('title'))
        self.heading('seeders', text='Seeders', command=lambda: self._sort_column('seeders', klass=int))
        self.heading('leeches', text='Leeches', command=lambda: self._sort_column('leeches', klass=int))
        self.heading('downloaded', text='Downloaded', command=lambda: self._sort_column('downloaded', klass=int))

    def _sort_column(self, column, reverse=False, klass: type = str):
        items = [(self.set(k, column), k) for k in self.get_children('')]
        items.sort(reverse=reverse, key=lambda item: klass(item[0]))

        # rearrange items in sorted positions
        for index, (val, k) in enumerate(items):
            self.move(k, '', index)

        # reverse sort next time
        self.heading(column, command=lambda: self._sort_column(column, not reverse, klass))

    def _values_of(self, tnt_entry: TntEntry):
        return [tnt_entry._asdict()[column] for column in self.columns]

    def add(self, tnt_entry: TntEntry):
        return self.insert('', 'end', values=self._values_of(tnt_entry))


class ConnectionLabel(tk.Label):
    def __init__(self, master, **option):
        super().__init__(master, **option)
        self._disconnected_image = tk.BitmapImage(file='images/disconnected.xbm')
        self._connected_image = tk.BitmapImage(file='images/connected.xbm')
        self.config(image=self._disconnected_image)

    def connected(self):
        self.config(image=self._connected_image)

    def disconnected(self):
        self.config(image=self._connected_image)


class CrawlerFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self._client = Client()
        self._magnets = []

        top_frame = tk.Frame(self)
        top_frame.columnconfigure(1, weight=1)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(top_frame, text='Keyword:').grid(row=0, column=0, sticky='E', padx=3)
        self._keyword_var = tk.StringVar()
        self._keyword_entry = tk.Entry(top_frame, textvariable=self._keyword_var)
        self._keyword_entry.grid(row=0, column=1, sticky='WE', padx=3)
        self._search_button = tk.Button(top_frame, text='Search')
        self._search_button.grid(row=0, column=2, sticky='W', padx=3)
        self._search_button.config(command=self._start_crawler)

        bottom_frame = tk.Frame(self)
        bottom_frame.columnconfigure(0, weight=1)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_var = tk.Variable()
        tk.Label(bottom_frame, bd=1, anchor=tk.W, textvariable=self._status_var).grid(row=0, column=0, sticky='WE')
        self._connection_label = ConnectionLabel(bottom_frame)
        self._connection_label.grid(row=0, column=1)

        middle_frame = tk.Frame(self)
        middle_frame.pack(expand=tk.YES, fill=tk.BOTH)

        self._treeview = TntTreeview(middle_frame)
        scrollbar = ttk.Scrollbar(middle_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar.config(command=self._treeview.yview)
        self._treeview.config(yscrollcommand=scrollbar.set)
        self._treeview.pack(expand=tk.YES, fill=tk.BOTH)

        # self.treeview_menu = tk.Menu(self.treeview)
        # self.treeview_menu.add_command(label='Download selected', command=self._download_selection())
        # self.treeview.bind('<Button-3>', )

        self.pack(expand=tk.YES, fill=tk.BOTH)

        # self._stop_event = threading.Event()
        # self._check_thread = threading.Thread(target=self._check_transmission_connection)
        self._crawler_task = CrawlerTask()

    def _clear_magnets(self):
        self._treeview.delete(*self._treeview.get_children())
        self._magnets.clear()

    # def shutdown(self):
    #     self._crawler_thread.join()
    #
    # def _check_transmission_connection(self):
    #     while not self._stop_event.is_set():
    #         try:
    #             self.client.list()
    #             self.status_bar.connected()
    #         except requests.exceptions.ConnectionError:
    #             self.status_bar.disconnected()
    #         time.sleep(1)
    #
    # def _download_selection(self):
    #     items = self.output_frame.selection()
    #     for item in items:
    #         try:
    #             self.client.torrent.add(filename=self.magnets[item])
    #         except requests.exceptions.ConnectionError:
    #             self.status_bar.disconnected()
    #
    def _start_crawler(self):
        self._clear_magnets()
        self._crawler_task.start(self._keyword_var.get())
        self.master.after(1000, self._process_queue)
        self._start_downloading()

    def _process_queue(self):
        try:
            while True:
                tnt_entry: TntEntry = self._crawler_task.queue.get_nowait()
                if tnt_entry is None:
                    self._stop_downloading()
                    break
                self._treeview.add(tnt_entry)
                self._magnets.append(tnt_entry.magnet)
                self._treeview.update_idletasks()
        except Empty:
            self._treeview.after(100, self._process_queue)

    def _start_downloading(self):
        self._status_var.set('Downloading...')
        self._keyword_entry.config(state=tk.DISABLED)
        # self._search_button.config(state=tk.DISABLED)
        self._search_button.config(command=self._crawler_task.stop, text='Stop')

    def _stop_downloading(self):
        self._status_var.set('Done: {} magnets downloaded'.format(len(self._magnets)))
        self._keyword_entry.config(state=tk.NORMAL)
        # self._search_button.config(state=tk.NORMAL)
        self._search_button.config(command=self._start_crawler, text='Search')


def main():
    root = tk.Tk()
    root.wm_title('TNT Crawler')
    CrawlerFrame(master=root).mainloop()


if __name__ == '__main__':
    main()
