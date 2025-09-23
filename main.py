import os
import re
import tkinter as tk
from tkinter import filedialog, Text, Scrollbar
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import html

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

POINTS_FILE = "point_250923.txt"
API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
KONAMI_DB_BASE = "https://www.db.yugioh-card.com"
KONAMI_DB_SEARCH_URL = KONAMI_DB_BASE + "/yugiohdb/card_search.action?ope=1&sess=1&rp=10&mode=&sort=1&keyword={}"
MAX_WORKERS = 10

def get_korean_name_from_konami(english_name):
    try:
        keyword = urllib.parse.quote_plus(english_name)
        search_url = KONAMI_DB_SEARCH_URL.format(keyword)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        search_resp = requests.get(search_url, headers=headers, timeout=10)
        search_resp.raise_for_status()
        html_text = search_resp.text

        pair_pattern = re.compile(
            r'class="cnm"\s+value=[\'\"]([^\'\"]+)[\'\"][\s\S]*?class="link_value"\s+value=[\'\"]([^\'\"]+)[\'\"]',
            re.DOTALL
        )
        candidates = pair_pattern.findall(html_text)
        if not candidates:
            return None

        selected_relative = None
        for cnm_value, link_value in candidates:
            cnm_unescaped = html.unescape(cnm_value).strip()
            if cnm_unescaped == english_name:
                selected_relative = link_value
                break
        if selected_relative is None:
            selected_relative = candidates[0][1]

        detail_url = KONAMI_DB_BASE + selected_relative + "&request_locale=ko"
        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
        detail_resp.raise_for_status()
        detail_html = detail_resp.text

        tm = re.search(r'<title>([^<]+)</title>', detail_html, re.IGNORECASE)
        if not tm:
            return None
        title_text = tm.group(1).strip()
        korean_name = title_text.split('|')[0].strip()
        return korean_name if korean_name else None
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None

def fetch_card_data(passcode, points, options, app_instance):
    card_name_ko = f"알 수 없는 카드 ({passcode})"
    card_name_en = None
    score = 0

    try:
        params_en = {'id': passcode}
        response_en = requests.get(API_URL, params=params_en, timeout=5)
        response_en.raise_for_status()
        card_data = response_en.json()['data'][0]
        card_name_en = card_data.get('name')
        card_name_ko = card_name_en
        
        params_ko = {'language': 'ko', 'id': passcode}
        response_ko = requests.get(API_URL, params=params_ko, timeout=5)
        if response_ko.status_code == 200:
            card_data_ko = response_ko.json()['data'][0]
            card_name_ko = card_data_ko.get('name', card_name_en)
        
        if card_name_ko == card_name_en and options['scrape_yugipedia']:
            app_instance.root.after(0, lambda: app_instance.status_label.config(text=f"KONAMI DB 검색 중: {card_name_en}"))
            scraped_name = get_korean_name_from_konami(card_name_en)
            if scraped_name:
                card_name_ko = scraped_name

    except (requests.exceptions.RequestException, IndexError, KeyError):
        pass 

    if card_name_en:
        score = points.get(card_name_en, 0)
    
    if not options['show_zero_points'] and score == 0:
        return None 

    return (card_name_ko, score)

def load_points(app):
    points = {}
    try:
        with open(resource_path(POINTS_FILE), "r", encoding="utf-8") as f:
            next(f)
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    points[parts[0].strip()] = int(parts[1].strip())
    except FileNotFoundError:
        app.show_error(f"오류: {POINTS_FILE} 파일을 찾을 수 없습니다.")
        return None
    return points

def calculate_deck_score_api(ydk_file, points, result_text_widget, app_instance, options):
    try:
        app_instance.root.after(0, lambda: app_instance.calculate_btn.config(state=tk.DISABLED))
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="계산 중..."))

        result_text_widget.config(state=tk.NORMAL)
        result_text_widget.delete(1.0, tk.END)
        
        main_deck_passcodes = []
        side_deck_passcodes = []
        is_side_deck = False

        with open(ydk_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line == "!side":
                    is_side_deck = True
                    continue
                if line.startswith(('#', '!')) or not line:
                    continue
                
                if is_side_deck:
                    side_deck_passcodes.append(line)
                else:
                    main_deck_passcodes.append(line)

        main_deck_cards_to_display = []
        main_deck_total_score = 0
        side_deck_cards_to_display = []
        side_deck_total_score = 0
        grand_total_score = 0

        app_instance.root.after(0, lambda: app_instance.status_label.config(text="메인 덱 카드 정보 가져오는 중..."))
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            fetch_func = lambda p: fetch_card_data(p, points, options, app_instance)
            main_deck_results = list(executor.map(fetch_func, main_deck_passcodes))

        for result in main_deck_results:
            if result is not None:
                name, score = result
                main_deck_cards_to_display.append((name, score))
                main_deck_total_score += score

        if options['include_side_deck'] and side_deck_passcodes:
            app_instance.root.after(0, lambda: app_instance.status_label.config(text="사이드 덱 카드 정보 가져오는 중..."))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                fetch_func = lambda p: fetch_card_data(p, points, options, app_instance)
                side_deck_results = list(executor.map(fetch_func, side_deck_passcodes))

            for result in side_deck_results:
                if result is not None:
                    name, score = result
                    side_deck_cards_to_display.append((name, score))
                    side_deck_total_score += score

        result_text_widget.insert(tk.END, f"--- 메인 덱 ({os.path.basename(ydk_file)}) ---\n")
        for name, score in main_deck_cards_to_display:
            result_text_widget.insert(tk.END, f"{name} - {score}\n")
        result_text_widget.insert(tk.END, f"\n메인 덱 총 포인트: {main_deck_total_score}\n")

        if options['include_side_deck']:
            result_text_widget.insert(tk.END, f"\n--- 사이드 덱 ({os.path.basename(ydk_file)}) ---\n")
            for name, score in side_deck_cards_to_display:
                result_text_widget.insert(tk.END, f"{name} - {score}\n")
            result_text_widget.insert(tk.END, f"\n사이드 덱 총 포인트: {side_deck_total_score}\n")

        grand_total_score = main_deck_total_score + side_deck_total_score
        result_text_widget.insert(tk.END, f"\n--- 전체 총 점수: {grand_total_score} ---\n")

    except Exception as e:
        result_text_widget.insert(tk.END, f"오류 발생: {e}\n")
    finally:
        result_text_widget.config(state=tk.DISABLED)
        app_instance.root.after(0, lambda: app_instance.calculate_btn.config(state=tk.NORMAL))
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="준비 완료."))

class YdkPointCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("메타파이즈 지원좀")
        self.root.geometry("500x700")

        self.points = None
        self.deck_folder = ""

        self.main_frame = tk.Frame(root, padx=10, pady=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(self.main_frame, text="초기화 중...", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.folder_frame = tk.Frame(self.main_frame)
        self.folder_frame.pack(fill=tk.X, pady=(0, 5))
        self.select_folder_btn = tk.Button(self.folder_frame, text="덱 폴더 선택", command=self.select_folder)
        self.select_folder_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.folder_label = tk.Label(self.folder_frame, text="선택된 폴더 없음", wraplength=300, justify=tk.LEFT)
        self.folder_label.pack(side=tk.LEFT, padx=(10, 0))

        self.options_frame = tk.LabelFrame(self.main_frame, text="옵션", padx=5, pady=5)
        self.options_frame.pack(fill=tk.X, pady=5)

        self.show_zero_points = tk.BooleanVar(value=False)
        self.show_zero_points_check = tk.Checkbutton(self.options_frame, text="0점 카드 표시", variable=self.show_zero_points)
        self.show_zero_points_check.pack(side=tk.LEFT)

        self.scrape_yugipedia = tk.BooleanVar(value=True)
        self.scrape_yugipedia_check = tk.Checkbutton(self.options_frame, text="DB 누락 카드 한글화 (느림)", variable=self.scrape_yugipedia)
        self.scrape_yugipedia_check.pack(side=tk.LEFT, padx=(10, 0))

        self.include_side_deck = tk.BooleanVar(value=False)
        self.include_side_deck_check = tk.Checkbutton(self.options_frame, text="사이드 덱 포함", variable=self.include_side_deck)
        self.include_side_deck_check.pack(side=tk.LEFT, padx=(10, 0))

        self.list_frame = tk.Frame(self.main_frame)
        self.list_frame.pack(fill=tk.BOTH, expand=True)
        self.deck_list_label = tk.Label(self.list_frame, text="YDK 파일 목록:")
        self.deck_list_label.pack(anchor=tk.W)
        self.deck_listbox = tk.Listbox(self.list_frame)
        self.deck_listbox.pack(fill=tk.BOTH, expand=True)

        self.calculate_btn = tk.Button(self.main_frame, text="포인트 계산", command=self.calculate_score_gui, state=tk.DISABLED)
        self.calculate_btn.pack(fill=tk.X, pady=5)

        self.result_frame = tk.Frame(self.main_frame)
        self.result_frame.pack(fill=tk.BOTH, expand=True)
        self.result_label = tk.Label(self.result_frame, text="총 포인트:")
        self.result_label.pack(anchor=tk.W)
        self.result_text = Text(self.result_frame, height=15, state=tk.DISABLED, wrap=tk.WORD)
        self.scrollbar = Scrollbar(self.result_frame, command=self.result_text.yview)
        self.result_text.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.initialize_app()

    def initialize_app(self):
        self.status_label.config(text="포인트 파일 로딩 중...")
        self.points = load_points(self)
        if self.points is not None:
            self.calculate_btn.config(state=tk.NORMAL)
            self.status_label.config(text="준비 완료.")
        else:
            self.status_label.config(text="오류: 포인트 파일을 불러올 수 없습니다.")

    def select_folder(self):
        self.deck_folder = filedialog.askdirectory()
        if self.deck_folder:
            self.folder_label.config(text=self.deck_folder)
            self.update_deck_list()

    def update_deck_list(self):
        self.deck_listbox.delete(0, tk.END)
        try:
            ydk_files = [f for f in os.listdir(self.deck_folder) if f.endswith(".ydk")]
            for ydk_file in ydk_files:
                self.deck_listbox.insert(tk.END, ydk_file)
        except Exception as e:
            self.show_error(f"폴더를 읽는 중 오류 발생: {e}")

    def calculate_score_gui(self):
        selected_indices = self.deck_listbox.curselection()
        if not selected_indices:
            self.show_error("목록에서 YDK 파일을 선택해주세요.")
            return
        
        if self.points is None:
            self.show_error("포인트 파일이 올바르게 로드되지 않았습니다. 프로그램을 재시작해주세요.")
            return

        selected_file = self.deck_listbox.get(selected_indices[0])
        full_path = os.path.join(self.deck_folder, selected_file)
        
        options = {
            'show_zero_points': self.show_zero_points.get(),
            'scrape_yugipedia': self.scrape_yugipedia.get(),
            'include_side_deck': self.include_side_deck.get()
        }

        threading.Thread(target=calculate_deck_score_api, args=(full_path, self.points, self.result_text, self, options), daemon=True).start()

    def show_error(self, message):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"오류:\n{message}")
        self.result_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = YdkPointCalculatorApp(root)
    root.mainloop()
