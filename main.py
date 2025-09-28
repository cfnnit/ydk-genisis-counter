import os
import re
import tkinter as tk
from tkinter import filedialog, Text, Scrollbar, ttk
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import html
import json
import sys
import time
import pickle
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
KONAMI_DB_BASE = "https://www.db.yugioh-card.com"
KONAMI_DB_SEARCH_URL = KONAMI_DB_BASE + "/yugiohdb/card_search.action?ope=1&sess=1&rp=10&mode=&sort=1&keyword={}"
MAX_WORKERS = 20
GITHUB_API_URL = "https://api.github.com/repos/cfnnit/ydk-genisis-counter/contents/point%20rule"

GITHUB_HEADERS = {
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'YDK-Point-Calculator'
}

KONAMI_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

korean_name_cache = {}
card_data_cache = {}

def save_caches(app_instance=None):
    if app_instance and not app_instance.save_cache.get():
        return
        
    try:
        cache_data = {
            'korean_name_cache': korean_name_cache,
            'card_data_cache': card_data_cache
        }
        with open(resource_path('cache.pkl'), 'wb') as f:
            pickle.dump(cache_data, f)
    except Exception as e:
        print(f"캐시 저장 오류: {e}")

def load_caches():
    global korean_name_cache, card_data_cache
    try:
        with open(resource_path('cache.pkl'), 'rb') as f:
            cache_data = pickle.load(f)
            korean_name_cache = cache_data.get('korean_name_cache', {})
            card_data_cache = cache_data.get('card_data_cache', {})
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"캐시 로드 오류: {e}")

def clear_caches():
    korean_name_cache.clear()
    card_data_cache.clear()
    try:
        if os.path.exists(resource_path('cache.pkl')):
            os.remove(resource_path('cache.pkl'))
    except Exception:
        pass
    print("캐시가 초기화되었습니다.")

def get_points_files_from_github():
    try:
        response = requests.get(GITHUB_API_URL, headers=GITHUB_HEADERS, timeout=10)
        response.raise_for_status()
        
        files = response.json()
        points_files = []
        
        for file_info in files:
            if file_info['type'] == 'file' and file_info['name'].endswith('.txt'):
                date_match = re.search(r'^(\d+)\.txt$', file_info['name'])
                if date_match:
                    date_str = date_match.group(1)
                    points_files.append({
                        'filename': file_info['name'],
                        'date': date_str,
                        'download_url': file_info['download_url']
                    })
        
        points_files.sort(key=lambda x: x['date'], reverse=True)
        return points_files
        
    except requests.exceptions.RequestException as e:
        print(f"GitHub API 요청 오류: {e}")
        return []
    except Exception as e:
        print(f"포인트 파일 목록 가져오기 오류: {e}")
        return []

def download_points_file(download_url, filename):
    try:
        headers = GITHUB_HEADERS.copy()
        headers['Accept'] = 'application/vnd.github.v3.raw'
        
        response = requests.get(download_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        file_path = resource_path(filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        return True
    except Exception as e:
        print(f"포인트 파일 다운로드 오류: {e}")
        return False

def get_korean_name_from_konami(english_name):
    if english_name in korean_name_cache:
        return korean_name_cache[english_name]
    
    try:
        keyword = urllib.parse.quote_plus(english_name)
        search_url = KONAMI_DB_SEARCH_URL.format(keyword)
        
        search_resp = requests.get(search_url, headers=KONAMI_HEADERS, timeout=10)
        search_resp.raise_for_status()
        
        pair_pattern = re.compile(
            r'class="cnm"\s+value=[\'\"]([^\'\"]+)[\'\"][\s\S]*?class="link_value"\s+value=[\'\"]([^\'\"]+)[\'\"]',
            re.DOTALL
        )
        candidates = pair_pattern.findall(search_resp.text)
        if not candidates:
            korean_name_cache[english_name] = None
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
        detail_resp = requests.get(detail_url, headers=KONAMI_HEADERS, timeout=10)
        detail_resp.raise_for_status()

        title_match = re.search(r'<title>([^<]+)</title>', detail_resp.text, re.IGNORECASE)
        if not title_match:
            korean_name_cache[english_name] = None
            return None
            
        title_text = title_match.group(1).strip()
        korean_name = title_text.split('|')[0].strip()
        result = korean_name if korean_name else None
        korean_name_cache[english_name] = result
        return result
        
    except requests.exceptions.RequestException:
        korean_name_cache[english_name] = None
        return None
    except Exception:
        korean_name_cache[english_name] = None
        return None

def get_english_name_from_cid(cid):
    cache_key = f"cid_{cid}"
    if cache_key in korean_name_cache:
        return korean_name_cache[cache_key]
    
    try:
        detail_url = f"{KONAMI_DB_BASE}/yugiohdb/card_search.action?ope=2&cid={cid}&request_locale=en"
        detail_resp = requests.get(detail_url, headers=KONAMI_HEADERS, timeout=5)
        detail_resp.raise_for_status()

        title_pattern = re.compile(r'<title>([^<]+)</title>', re.IGNORECASE)
        title_match = title_pattern.search(detail_resp.text)
        if not title_match:
            korean_name_cache[cache_key] = None
            return None
            
        title_text = title_match.group(1).strip()
        english_name = title_text.split('|')[0].strip()
        result = english_name if english_name else None
        korean_name_cache[cache_key] = result
        return result
        
    except requests.exceptions.RequestException:
        korean_name_cache[cache_key] = None
        return None
    except Exception:
        korean_name_cache[cache_key] = None
        return None

def extract_cards_from_html(html_content):
    cards = {
        'main': [],
        'side': [],
        'extra': []
    }

    main_pattern = re.compile(r'\$\("#detailtext_main[^"]*"[^}]*cid=(\d+)', re.IGNORECASE | re.DOTALL)
    extra_pattern = re.compile(r'\$\("#detailtext_ext[^"]*"[^}]*cid=(\d+)', re.IGNORECASE | re.DOTALL)
    side_pattern = re.compile(r'\$\("#detailtext_side[^"]*"[^}]*cid=(\d+)', re.IGNORECASE | re.DOTALL)
    all_cid_pattern = re.compile(r'cid=(\d+)', re.IGNORECASE)
    
    main_matches = main_pattern.findall(html_content)
    extra_matches = extra_pattern.findall(html_content)
    side_matches = side_pattern.findall(html_content)
    
    cards['main'].extend(main_matches)
    cards['extra'].extend(extra_matches)
    cards['side'].extend(side_matches)
    
    if not any(cards.values()):
        all_cids = all_cid_pattern.findall(html_content)
        
        chunk_size = 5000
        for i in range(0, len(html_content), chunk_size):
            chunk = html_content[i:i + chunk_size].lower()
            
            for cid in all_cids:
                if cid not in cards['main'] and cid not in cards['side'] and cid not in cards['extra']:
                    if 'detailtext_side' in chunk and cid in chunk:
                        cards['side'].append(cid)
                    elif 'detailtext_ext' in chunk and cid in chunk:
                        cards['extra'].append(cid)
                    elif 'detailtext_main' in chunk and cid in chunk:
                        cards['main'].append(cid)
    
    cards['main'] = list(set(cards['main']))
    cards['side'] = list(set(cards['side']))
    cards['extra'] = list(set(cards['extra']))
    
    return cards

def fetch_card_data_from_cid(cid, points, options, app_instance):
    cache_key = f"cid_{cid}_{options['scrape_yugipedia']}_{options['show_zero_points']}"
    if cache_key in card_data_cache:
        return card_data_cache[cache_key]
    
    card_name_ko = f"알 수 없는 카드 (cid:{cid})"
    card_name_en = None
    score = 0

    try:
        english_cache_key = f"cid_{cid}"
        if english_cache_key in korean_name_cache:
            card_name_en = korean_name_cache[english_cache_key]
        else:
            card_name_en = get_english_name_from_cid(cid)
            
        if not card_name_en:
            result = (card_name_ko, 0) if options['show_zero_points'] else None
            card_data_cache[cache_key] = result
            return result
            
        card_name_ko = card_name_en
        
        if options['scrape_yugipedia'] and card_name_en:
            if card_name_en in korean_name_cache:
                korean_name = korean_name_cache[card_name_en]
                if korean_name:
                    card_name_ko = korean_name
            else:
                scraped_name = get_korean_name_from_konami(card_name_en)
                if scraped_name:
                    card_name_ko = scraped_name

        score = points.get(card_name_en, 0)

    except Exception as e:
        print(f"cid {cid} 처리 중 오류: {e}")
    
    result = (card_name_ko, score) if (options['show_zero_points'] or score > 0) else None
    card_data_cache[cache_key] = result
    return result

def fetch_card_data(passcode, points, options, app_instance):
    cache_key = f"{passcode}_{options['scrape_yugipedia']}_{options['show_zero_points']}"
    if cache_key in card_data_cache:
        return card_data_cache[cache_key]
    
    card_name_ko = f"알 수 없는 카드 (password:{passcode})"
    card_name_en = None
    score = 0

    try:
        response_en = requests.get(API_URL, params={'id': passcode}, timeout=5)
        response_en.raise_for_status()
        card_data = response_en.json()['data'][0]
        card_name_en = card_data.get('name')
        card_name_ko = card_name_en
        
        response_ko = requests.get(API_URL, params={'language': 'ko', 'id': passcode}, timeout=5)
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
    
    result = (card_name_ko, score) if (options['show_zero_points'] or score > 0) else None
    card_data_cache[cache_key] = result
    return result

def calculate_url_score(url, points, result_text_widget, app_instance, options):
    try:
        app_instance.root.after(0, lambda: app_instance.calculate_url_btn.config(state=tk.DISABLED))
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="URL에서 덱 정보 가져오는 중..."))

        result_text_widget.config(state=tk.NORMAL)
        result_text_widget.delete(1.0, tk.END)
        
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="URL에서 덱 정보 다운로드 중..."))
        response = requests.get(url, headers=KONAMI_HEADERS, timeout=10)
        response.raise_for_status()
        html_content = response.text
        
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="HTML에서 카드 정보 추출 중..."))
        cards = extract_cards_from_html(html_content)
        
        total_cards = len(cards['main']) + len(cards['side']) + len(cards['extra'])
        print(f"발견된 카드: 메인 {len(cards['main'])}, 사이드 {len(cards['side'])}, 엑스트라 {len(cards['extra'])} (총 {total_cards}장)")
        
        main_deck_cards_to_display = []
        main_deck_total_score = 0
        side_deck_cards_to_display = []
        side_deck_total_score = 0
        extra_deck_cards_to_display = []
        extra_deck_total_score = 0
        
        if cards['main']:
            app_instance.root.after(0, lambda: app_instance.status_label.config(text=f"메인 덱 카드 정보 가져오는 중... ({len(cards['main'])}장)"))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                fetch_func = lambda cid: fetch_card_data_from_cid(cid, points, options, app_instance)
                main_deck_results = list(executor.map(fetch_func, cards['main']))
        else:
            main_deck_results = []

        for result in main_deck_results:
            if result is not None:
                name, score = result
                main_deck_cards_to_display.append((name, score))
                main_deck_total_score += score

        if cards['extra']:
            app_instance.root.after(0, lambda: app_instance.status_label.config(text=f"엑스트라 덱 카드 정보 가져오는 중... ({len(cards['extra'])}장)"))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                fetch_func = lambda cid: fetch_card_data_from_cid(cid, points, options, app_instance)
                extra_deck_results = list(executor.map(fetch_func, cards['extra']))

            for result in extra_deck_results:
                if result is not None:
                    name, score = result
                    extra_deck_cards_to_display.append((name, score))
                    extra_deck_total_score += score
        else:
            extra_deck_results = []

        if options['include_side_deck'] and cards['side']:
            app_instance.root.after(0, lambda: app_instance.status_label.config(text=f"사이드 덱 카드 정보 가져오는 중... ({len(cards['side'])}장)"))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                fetch_func = lambda cid: fetch_card_data_from_cid(cid, points, options, app_instance)
                side_deck_results = list(executor.map(fetch_func, cards['side']))

            for result in side_deck_results:
                if result is not None:
                    name, score = result
                    side_deck_cards_to_display.append((name, score))
                    side_deck_total_score += score
        else:
            side_deck_results = []

        result_text_widget.insert(tk.END, f"--- 메인 덱 ---\n")
        if options['aggregate_same_cards']:
            all_main_cards = main_deck_cards_to_display + extra_deck_cards_to_display
            aggregated_main = aggregate_cards(all_main_cards)
            for name, total_score, unit_score in aggregated_main:
                if "x" in name:
                    result_text_widget.insert(tk.END, f"{name} - {total_score} ({unit_score})\n")
                else:
                    result_text_widget.insert(tk.END, f"{name} - {total_score}\n")
        else:
            for name, score in main_deck_cards_to_display:
                result_text_widget.insert(tk.END, f"{name} - {score}\n")
            for name, score in extra_deck_cards_to_display:
                result_text_widget.insert(tk.END, f"{name} - {score}\n")
        
        main_and_extra_total = main_deck_total_score + extra_deck_total_score
        result_text_widget.insert(tk.END, f"\n메인 덱 포인트: {main_and_extra_total}\n")

        if options['include_side_deck'] and cards['side']:
            result_text_widget.insert(tk.END, f"\n--- 사이드 덱 ---\n")
            if options['aggregate_same_cards']:
                aggregated_side = aggregate_cards(side_deck_cards_to_display)
                for name, total_score, unit_score in aggregated_side:
                    if "x" in name:
                        result_text_widget.insert(tk.END, f"{name} - {total_score} ({unit_score})\n")
                    else:
                        result_text_widget.insert(tk.END, f"{name} - {total_score}\n")
            else:
                for name, score in side_deck_cards_to_display:
                    result_text_widget.insert(tk.END, f"{name} - {score}\n")
            result_text_widget.insert(tk.END, f"\n사이드 덱 포인트: {side_deck_total_score}\n")

        grand_total_score = main_and_extra_total + side_deck_total_score
        result_text_widget.insert(tk.END, f"\n--- 전체 포인트: {grand_total_score} ---\n")

    except Exception as e:
        result_text_widget.insert(tk.END, f"오류 발생: {e}\n")
    finally:
        save_caches(app_instance)
        result_text_widget.config(state=tk.DISABLED)
        app_instance.root.after(0, lambda: app_instance.calculate_url_btn.config(state=tk.NORMAL))
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="준비 완료."))

def aggregate_cards(cards_list):
    card_count = {}
    for name, score in cards_list:
        if name in card_count:
            card_count[name]['count'] += 1
            card_count[name]['total_score'] += score
        else:
            card_count[name] = {'count': 1, 'total_score': score, 'unit_score': score}
    
    aggregated = []
    for name, data in card_count.items():
        if data['count'] > 1:
            aggregated.append((f"{name} x{data['count']}", data['total_score'], data['unit_score']))
        else:
            aggregated.append((name, data['total_score'], data['unit_score']))
    
    return aggregated

def load_points(app, points_filename):
    points = {}
    
    try:
        with open(resource_path(points_filename), "r", encoding="utf-8") as f:
            next(f)
            for line_num, line in enumerate(f, start=2):
                line = line.strip()
                if not line:
                    continue
                    
                parts = line.split('\t')
                if len(parts) >= 2:
                    card_name = parts[0].strip()
                    point_str = parts[1].strip()
                    
                    if not card_name:
                        continue
                        
                    if not point_str:
                        points[card_name] = 0
                        continue
                        
                    try:
                        points[card_name] = int(point_str)
                    except ValueError:
                        print(f"경고: {points_filename} {line_num}번째 줄에서 잘못된 포인트 값 '{point_str}', 0으로 처리")
                        points[card_name] = 0
                else:
                    print(f"경고: {points_filename} {line_num}번째 줄 형식 오류, 건너뜀: {line}")
                    
    except FileNotFoundError:
        if hasattr(app, 'show_error'):
            app.show_error(f"오류: {points_filename} 파일을 찾을 수 없습니다.")
        return None
    except Exception as e:
        if hasattr(app, 'show_error'):
            app.show_error(f"오류: {points_filename} 파일을 읽는 중 오류 발생: {e}")
        return None
    
    return points

class DeckFileHandler(FileSystemEventHandler):
    def __init__(self, app_instance):
        self.app_instance = app_instance
        self.last_modified = {}
        
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.ydk'):
            file_path = event.src_path
            current_time = time.time()
            
            if file_path in self.last_modified:
                if current_time - self.last_modified[file_path] < 1.0:
                    return
                    
            self.last_modified[file_path] = current_time
            
            if self.app_instance.auto_calculate.get() and self.app_instance.current_selected_file:
                if os.path.basename(file_path) == self.app_instance.current_selected_file:
                    self.app_instance.root.after(0, self.app_instance.auto_calculate_deck)
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.ydk'):
            self.app_instance.root.after(0, self.app_instance.update_deck_list)

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

        result_text_widget.insert(tk.END, f"--- 메인 덱 ---\n")
        if options['aggregate_same_cards']:
            aggregated_main = aggregate_cards(main_deck_cards_to_display)
            for name, total_score, unit_score in aggregated_main:
                if "x" in name:
                    result_text_widget.insert(tk.END, f"{name} - {total_score} ({unit_score})\n")
                else:
                    result_text_widget.insert(tk.END, f"{name} - {total_score}\n")
        else:
            for name, score in main_deck_cards_to_display:
                result_text_widget.insert(tk.END, f"{name} - {score}\n")
        result_text_widget.insert(tk.END, f"\n메인 덱 포인트: {main_deck_total_score}\n")

        if options['include_side_deck']:
            result_text_widget.insert(tk.END, f"\n--- 사이드 덱 ---\n")
            if options['aggregate_same_cards']:
                aggregated_side = aggregate_cards(side_deck_cards_to_display)
                for name, total_score, unit_score in aggregated_side:
                    if "x" in name:
                        result_text_widget.insert(tk.END, f"{name} - {total_score} ({unit_score})\n")
                    else:
                        result_text_widget.insert(tk.END, f"{name} - {total_score}\n")
            else:
                for name, score in side_deck_cards_to_display:
                    result_text_widget.insert(tk.END, f"{name} - {score}\n")
            result_text_widget.insert(tk.END, f"\n사이드 덱 포인트: {side_deck_total_score}\n")

        grand_total_score = main_deck_total_score + side_deck_total_score
        result_text_widget.insert(tk.END, f"\n--- 전체 포인트: {grand_total_score} ---\n")

    except Exception as e:
        result_text_widget.insert(tk.END, f"오류 발생: {e}\n")
    finally:
        save_caches(app_instance)
        result_text_widget.config(state=tk.DISABLED)
        app_instance.root.after(0, lambda: app_instance.calculate_btn.config(state=tk.NORMAL))
        app_instance.root.after(0, lambda: app_instance.status_label.config(text="준비 완료."))

class YdkPointCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("메타파이즈 지원좀")
        self.root.geometry("700x950")

        self.points = None
        self.deck_folder = ""
        self.points_files = []
        self.current_points_file = None
        self.all_deck_files = []
        self.current_selected_file = None
        self.file_watcher = None  

        self.main_frame = tk.Frame(root, padx=10, pady=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(self.main_frame, text="초기화 중...", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.points_frame = tk.LabelFrame(self.main_frame, text="제네시스 포인트 룰", padx=5, pady=5)
        self.points_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.points_combo = ttk.Combobox(self.points_frame, state="readonly", width=40)
        self.points_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.points_combo.bind("<<ComboboxSelected>>", self.on_points_file_selected)
        
        self.refresh_points_btn = tk.Button(self.points_frame, text="새로고침", command=self.refresh_points_files, width=10)
        self.refresh_points_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.folder_frame = tk.Frame(self.main_frame)
        self.folder_frame.pack(fill=tk.X, pady=(0, 5))
        self.select_folder_btn = tk.Button(self.folder_frame, text="덱 폴더 선택", command=self.select_folder)
        self.select_folder_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.folder_label = tk.Label(self.folder_frame, text="선택된 폴더 없음", wraplength=300, justify=tk.LEFT)
        self.folder_label.pack(side=tk.LEFT, padx=(10, 0))

        self.url_frame = tk.LabelFrame(self.main_frame, text="뉴런 URL 계산", padx=5, pady=5)
        self.url_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.url_entry = tk.Entry(self.url_frame, width=60)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.url_entry.insert(0, "덱 제목 아래의 링크를 복사하세요. 뉴런 자체 오류, 누락으로인한 카드 누락에 주의")
        self.url_entry.bind('<FocusIn>', self.on_url_entry_focus_in)
        self.url_entry.bind('<FocusOut>', self.on_url_entry_focus_out)
        
        self.calculate_url_btn = tk.Button(self.url_frame, text="입력", command=self.calculate_url_score, state=tk.DISABLED)
        self.calculate_url_btn.pack(side=tk.RIGHT)

        self.options_frame = tk.LabelFrame(self.main_frame, text="옵션", padx=5, pady=5)
        self.options_frame.pack(fill=tk.X, pady=5)

        self.aggregate_same_cards = tk.BooleanVar(value=True)
        self.aggregate_same_cards_check = tk.Checkbutton(self.options_frame, text="동일 카드 점수 합산", variable=self.aggregate_same_cards)
        self.aggregate_same_cards_check.pack(side=tk.LEFT, padx=(10, 0))

        self.show_zero_points = tk.BooleanVar(value=False)
        self.show_zero_points_check = tk.Checkbutton(self.options_frame, text="0점 카드 표시", variable=self.show_zero_points)
        self.show_zero_points_check.pack(side=tk.LEFT)

        self.include_side_deck = tk.BooleanVar(value=False)
        self.include_side_deck_check = tk.Checkbutton(self.options_frame, text="사이드 덱 포함", variable=self.include_side_deck)
        self.include_side_deck_check.pack(side=tk.LEFT, padx=(10, 0))

        self.scrape_yugipedia = tk.BooleanVar(value=True)
        self.scrape_yugipedia_check = tk.Checkbutton(self.options_frame, text="DB 누락 카드 한글화", variable=self.scrape_yugipedia)
        self.scrape_yugipedia_check.pack(side=tk.LEFT, padx=(10, 0))

        self.save_cache = tk.BooleanVar(value=True)
        self.save_cache_check = tk.Checkbutton(self.options_frame, text="카드 정보 기억", variable=self.save_cache)
        self.save_cache_check.pack(side=tk.LEFT, padx=(10, 0))

        self.list_frame = tk.Frame(self.main_frame)
        self.list_frame.pack(fill=tk.X, pady=5)
        self.deck_list_label = tk.Label(self.list_frame, text="YDK 파일 목록:")
        self.deck_list_label.pack(anchor=tk.W)
        
        self.search_frame = tk.Frame(self.list_frame)
        self.search_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_deck_list)
        self.search_entry = tk.Entry(self.search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.auto_calculate = tk.BooleanVar(value=False)
        self.auto_calculate_check = tk.Checkbutton(self.search_frame, text="덱 수정시 자동 계산", variable=self.auto_calculate)
        self.auto_calculate_check.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.deck_listbox = tk.Listbox(self.list_frame, height=8)
        self.deck_listbox.pack(fill=tk.X)

        self.calculate_btn = tk.Button(self.main_frame, text="포인트 계산", command=self.calculate_score_gui, state=tk.DISABLED)
        self.calculate_btn.pack(fill=tk.X, pady=5)

        self.result_frame = tk.Frame(self.main_frame)
        self.result_frame.pack(fill=tk.BOTH, expand=True)
        self.result_label = tk.Label(self.result_frame, text="결과:")
        self.result_label.pack(anchor=tk.W)
        self.result_text = Text(self.result_frame, height=20, state=tk.DISABLED, wrap=tk.WORD)
        self.scrollbar = Scrollbar(self.result_frame, command=self.result_text.yview)
        self.result_text.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        load_caches()
        self.initialize_app()
        
        self.url_entry.config(fg='gray')

    def initialize_app(self):
        self.status_label.config(text="포인트 파일 목록 가져오는 중...")
        threading.Thread(target=self.load_points_files_background, daemon=True).start()

    def load_points_files_background(self):
        try:
            self.points_files = get_points_files_from_github()
            if self.points_files:
                self.root.after(0, self.update_points_combo)
            else:
                self.root.after(0, lambda: self.status_label.config(text="오류: 포인트 파일 목록을 가져올 수 없습니다."))
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"오류: {str(e)}"))

    def update_points_combo(self):
        if not self.points_files:
            return

        file_display_names = []
        for file_info in self.points_files:
            date_str = file_info['date']
            if len(date_str) == 6:
                formatted_date = f"20{date_str[:2]}.{date_str[2:4]}.{date_str[4:6]}"
            else:
                formatted_date = date_str
            file_display_names.append(f"{formatted_date} ({file_info['filename']})")
        
        self.points_combo['values'] = file_display_names
        
        if file_display_names:
            self.points_combo.current(0)
            self.on_points_file_selected(None)
        else:
            self.status_label.config(text="포인트 파일이 없습니다.")

    def refresh_points_files(self):
        self.status_label.config(text="포인트 파일 목록 새로고침 중...")
        threading.Thread(target=self.load_points_files_background, daemon=True).start()

    def on_points_file_selected(self, event):
        selected_index = self.points_combo.current()
        if selected_index >= 0 and selected_index < len(self.points_files):
            selected_file = self.points_files[selected_index]
            self.current_points_file = selected_file
            self.status_label.config(text=f"포인트 파일 다운로드 중: {selected_file['filename']}")
            
            threading.Thread(target=self.load_selected_points_file, daemon=True).start()

    def load_selected_points_file(self):
        try:
            if not self.current_points_file:
                return
                
            success = download_points_file(
                self.current_points_file['download_url'], 
                self.current_points_file['filename']
            )
            
            if success:
                clear_caches()
                self.points = load_points(self, self.current_points_file['filename'])
                if self.points is not None:
                    self.root.after(0, lambda: self.calculate_btn.config(state=tk.NORMAL))
                    self.root.after(0, lambda: self.calculate_url_btn.config(state=tk.NORMAL))
                    self.root.after(0, lambda: self.status_label.config(text=f"포인트 파일 로드 완료: {self.current_points_file['filename']}"))
                else:
                    self.root.after(0, lambda: self.status_label.config(text="오류: 포인트 파일을 불러올 수 없습니다."))
            else:
                self.root.after(0, lambda: self.status_label.config(text="오류: 포인트 파일 다운로드 실패"))
                
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"오류: {str(e)}"))

    def select_folder(self):
        self.deck_folder = filedialog.askdirectory()
        if self.deck_folder:
            self.folder_label.config(text=self.deck_folder)
            self.start_file_watcher()
            self.update_deck_list()

    def update_deck_list(self):
        self.deck_listbox.delete(0, tk.END)
        try:
            ydk_files = [f for f in os.listdir(self.deck_folder) if f.endswith(".ydk")]
            self.all_deck_files = ydk_files
            self.filter_deck_list()
        except Exception as e:
            self.show_error(f"폴더를 읽는 중 오류 발생: {e}")
    
    def filter_deck_list(self, *args):
        search_text = self.search_var.get().lower()
        self.deck_listbox.delete(0, tk.END)
        
        filtered_files = [f for f in self.all_deck_files if search_text in f.lower()]
        for ydk_file in filtered_files:
            self.deck_listbox.insert(tk.END, ydk_file)
    
    def start_file_watcher(self):
        if self.file_watcher:
            self.file_watcher.stop()
            
        if self.deck_folder:
            self.file_watcher = Observer()
            event_handler = DeckFileHandler(self)
            self.file_watcher.schedule(event_handler, self.deck_folder, recursive=False)
            self.file_watcher.start()
    
    def auto_calculate_deck(self):
        if self.points is None or not self.current_selected_file:
            return
            
        full_path = os.path.join(self.deck_folder, self.current_selected_file)
        
        options = {
            'show_zero_points': self.show_zero_points.get(),
            'scrape_yugipedia': self.scrape_yugipedia.get(),
            'include_side_deck': self.include_side_deck.get(),
            'aggregate_same_cards': self.aggregate_same_cards.get()
        }
        
        threading.Thread(target=calculate_deck_score_api, args=(full_path, self.points, self.result_text, self, options), daemon=True).start()


    def calculate_score_gui(self):
        selected_indices = self.deck_listbox.curselection()
        if not selected_indices:
            self.show_error("목록에서 YDK 파일을 선택해주세요.")
            return
        
        if self.points is None:
            self.show_error("포인트 파일이 올바르게 로드되지 않았습니다. 프로그램을 재시작해주세요.")
            return

        selected_file = self.deck_listbox.get(selected_indices[0])
        self.current_selected_file = selected_file
        full_path = os.path.join(self.deck_folder, selected_file)
        
        options = {
            'show_zero_points': self.show_zero_points.get(),
            'scrape_yugipedia': self.scrape_yugipedia.get(),
            'include_side_deck': self.include_side_deck.get(),
            'aggregate_same_cards': self.aggregate_same_cards.get()
        }

        threading.Thread(target=calculate_deck_score_api, args=(full_path, self.points, self.result_text, self, options), daemon=True).start()

    def on_url_entry_focus_in(self, event):
        if self.url_entry.get() == "덱 제목 아래의 링크를 복사하세요. 뉴런 자체 오류, 누락으로인한 카드 누락에 주의":
            self.url_entry.delete(0, tk.END)
            self.url_entry.config(fg='black')

    def on_url_entry_focus_out(self, event):
        """URL 입력창 포커스 아웃 이벤트"""
        if not self.url_entry.get():
            self.url_entry.insert(0, "덱 제목 아래의 링크를 복사하세요. 뉴런 자체 오류, 누락으로인한 카드 누락에 주의")
            self.url_entry.config(fg='gray')

    def calculate_url_score(self):
        url = self.url_entry.get().strip()
        if not url or url == "덱 제목 아래의 링크를 복사하세요. 뉴런 자체 오류, 누락으로인한 카드 누락에 주의":
            self.show_error("URL을 입력해주세요.")
            return
        
        if self.points is None:
            self.show_error("포인트 파일이 올바르게 로드되지 않았습니다. 포인트 파일을 먼저 선택해주세요.")
            return

        if not url.startswith('http'):
            self.show_error("올바른 URL을 입력해주세요.")
            return
        
        options = {
            'show_zero_points': self.show_zero_points.get(),
            'scrape_yugipedia': self.scrape_yugipedia.get(),
            'include_side_deck': self.include_side_deck.get(),
            'aggregate_same_cards': self.aggregate_same_cards.get()
        }

        threading.Thread(target=calculate_url_score, args=(url, self.points, self.result_text, self, options), daemon=True).start()

    def show_error(self, message):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"오류:\n{message}")
        self.result_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = YdkPointCalculatorApp(root)
    
    def on_closing():
        if app.file_watcher:
            app.file_watcher.stop()
        save_caches(app)
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
