from clutch.core import Client, TransmissionRPCError
from crawler import TntCrawler, TntWriter, TntEntry
from pkg_resources import resource_stream
from queue import Queue, Empty
from requests.exceptions import ConnectionError
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import asyncio
import time
import tkinter as tk
import threading


class QueuesWriter(TntWriter):
    def __init__(self, entries: Queue, pages: Queue):
        super().__init__()
        self._entries = entries
        self._pages = pages

    def entry_parsed(self, tnt_entry: TntEntry):
        self._entries.put(tnt_entry)

    def after_first_page(self, num_pages):
        self._pages.put(num_pages)

    def page_processed(self, page):
        self._pages.put(page)


class CrawlerThread(threading.Thread):
    def __init__(self, keyword):
        super().__init__()
        self.entries = Queue()
        self.pages = Queue()
        self._loop = asyncio.new_event_loop()
        self._tnt_crawler = TntCrawler(self._loop, QueuesWriter(self.entries, self.pages))
        self._keyword = keyword
        self.daemon = True

    def run(self):
        asyncio.set_event_loop(self._loop)
        self._tnt_crawler.setup(keyword=self._keyword, category=0)
        self._loop.run_until_complete(self._tnt_crawler.crawl())
        self._loop.close()
        self.entries.put(None)
        self.pages.put(None)

    def stop(self):
        self._tnt_crawler.stop()


class ClientThread(threading.Thread):

    delay_ms = 500

    def __init__(self, client: Client):
        super().__init__()
        self.queue = Queue()
        self._client = client
        self._connected = False
        self.daemon = True

    def _try_connection(self):
        try:
            self._client.list()
            if not self._connected:
                self.queue.put('connected')
                self._connected = True
        except ConnectionError:
            if self._connected:
                self.queue.put('disconnected')
                self._connected = False

    def run(self):
        while True:
            self._try_connection()
            time.sleep(self.delay_ms / 1000)


class TntTreeview(ttk.Treeview):

    columns = ('seeders', 'leeches', 'downloaded', 'title')

    def __init__(self, master):
        super().__init__(master, show='headings', columns=self.columns)

        self.heading('title', text='Title', command=lambda: self._sort_column('title'))
        self.heading('seeders', text='Seeders', command=lambda: self._sort_column('seeders', klass=int))
        self.heading('leeches', text='Leeches', command=lambda: self._sort_column('leeches', klass=int))
        self.heading('downloaded', text='Downloaded', command=lambda: self._sort_column('downloaded', klass=int))

        self.column(column='seeders', width=100, stretch=False, minwidth=100)
        self.column(column='leeches', width=100, stretch=False, minwidth=100)
        self.column(column='downloaded', width=100, stretch=False, minwidth=100)

        self.tag_configure('transmission', foreground='green')

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
        disconnected = Image.open(
            'images/disconnected.png').resize((20, 20), Image.ANTIALIAS)
        connected = Image.open(
            'images/connected.png').resize((20, 20), Image.ANTIALIAS)

        self._images = {'connected': ImageTk.PhotoImage(connected),
                        'disconnected': ImageTk.PhotoImage(disconnected)}

        self.config(image=self._images['disconnected'])

    def status(self, status):
        self.config(image=self._images[status])


class CrawlerFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self._client = Client()
        self._magnets = dict()
        self._client_thread = ClientThread(self._client)

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
        self._keyword_entry.bind('<Return>', lambda e: self._start_crawler())

        bottom_frame = tk.Frame(self)
        bottom_frame.columnconfigure(1, weight=1)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_var = tk.Variable()
        tk.Label(bottom_frame, bd=1, anchor=tk.W, textvariable=self._status_var).grid(row=0, column=0, sticky='WE')

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", thickness=5)
        self._progress_bar = ttk.Progressbar(bottom_frame, orient=tk.HORIZONTAL, style="TProgressbar",
                                             length=100, mode="determinate")

        self._connection_label = ConnectionLabel(bottom_frame)
        self._connection_label.grid(row=0, column=2)

        middle_frame = tk.Frame(self)
        middle_frame.pack(expand=tk.YES, fill=tk.BOTH)

        self._treeview = TntTreeview(middle_frame)
        scrollbar = ttk.Scrollbar(middle_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar.config(command=self._treeview.yview)
        self._treeview.config(yscrollcommand=scrollbar.set)
        self._treeview.pack(expand=tk.YES, fill=tk.BOTH)

        self._treeview_menu = tk.Menu(self._treeview, tearoff=0)
        self._treeview_menu.add_command(label='Download selected', command=self._download_selected_items)
        self._treeview.bind('<Button-3>', lambda e: self._treeview_menu.tk_popup(e.x_root, e.y_root))
        # TODO: no double click to whole treeview, it's allowed only on treeview's entries
        # self._treeview.bind('<Double-1>', lambda e: self._download_selected_items())

        self.pack(expand=tk.YES, fill=tk.BOTH)

        self._client_thread.start()
        self._connection_label.after(self._client_thread.delay_ms, self._process_connection)

    def _start_crawler(self):
        self._clear_magnets()
        self._status_var.set('Downloading...')
        self._keyword_entry.config(state=tk.DISABLED)
        crawler_thread = CrawlerThread(self._keyword_var.get())
        crawler_thread.start()
        self._search_button.config(command=crawler_thread.stop, text='Stop')
        self._treeview.after(1000, self._process_first_page, crawler_thread)

    def _process_connection(self):
        try:
            status = self._client_thread.queue.get_nowait()
            if status is None:
                return
            else:
                self._connection_label.status(status)
        except Empty:
            pass
        self._connection_label.after(self._client_thread.delay_ms, self._process_connection)

    def _process_first_page(self, crawler_thread: CrawlerThread):
        try:
            num_pages = crawler_thread.pages.get_nowait()
            if num_pages is None:
                self._crawler_stopped()
            else:
                self._process_entries(crawler_thread)
                if num_pages > 1:
                    self._status_var.set('Found {} pages: downloading...'.format(num_pages))
                    self._display_progress_bar(num_pages)
                    self._progress_bar.after(100, self._process_pages, crawler_thread)
        except Empty:
            self._treeview.after(100, self._process_first_page, crawler_thread)

    def _display_progress_bar(self, num_pages):
        self._progress_bar.config(maximum=num_pages, value=0)
        self._progress_bar.grid(row=0, column=1, sticky='E', padx=10)

    def _process_pages(self, crawler_thread: CrawlerThread):
        try:
            page = crawler_thread.pages.get_nowait()
            if page is None:
                self._progress_bar.grid_forget()
                return
            self._progress_bar['value'] += 1
        except Empty:
            pass
        self._progress_bar.after(200, self._process_pages, crawler_thread)

    def _process_entries(self, crawler_thread: CrawlerThread):
        try:
            while True:
                tnt_entry: TntEntry = crawler_thread.entries.get_nowait()
                if tnt_entry is None:
                    self._crawler_stopped()
                    break
                item = self._treeview.add(tnt_entry)
                self._magnets[item] = tnt_entry.magnet
                self._treeview.update_idletasks()
        except Empty:
            self._treeview.after(100, self._process_entries, crawler_thread)

    def _clear_magnets(self):
        self._treeview.delete(*self._treeview.get_children())
        self._magnets.clear()

    def _download_selected_items(self):
        items = self._treeview.selection()
        for item in items:
            try:
                magnet = self._magnets[item]
                self._client.torrent.add(filename=magnet)
                self._treeview.item(item, tags='transmission')
                print(magnet)
            except ConnectionError:
                messagebox.showwarning('Connection failed', 'transmission-daemon is unreachable')
                break
            except TransmissionRPCError as e:
                print(e)

    def _crawler_stopped(self):
        self._status_var.set('Done: downloaded {} magnets'.format(len(self._magnets)))
        self._keyword_entry.config(state=tk.NORMAL)
        self._search_button.config(command=self._start_crawler, text='Search')


def main():
    root = tk.Tk()
    root.wm_title('TNT Crawler')
    CrawlerFrame(master=root).mainloop()


if __name__ == '__main__':
    main()
