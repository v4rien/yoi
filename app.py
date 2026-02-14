import streamlit as st
import requests
import urllib3
from bs4 import BeautifulSoup
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Konfigurasi Halaman
st.set_page_config(page_title="Auto KRS UIN Malang (Web)", layout="wide")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- STATE MANAGEMENT ---
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'running' not in st.session_state:
    st.session_state.running = False
if 'success_list' not in st.session_state:
    st.session_state.success_list = set()

# --- CORE FUNCTIONS ---

def request_with_retry(url, method="GET", data=None, cookie_str="", retry_wait=0.01):
    headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}
    while True:
        try:
            if method == "POST":
                return requests.post(url, headers=headers, data=data, verify=False, timeout=5)
            return requests.get(url, headers=headers, verify=False, timeout=5)
        except:
            time.sleep(retry_wait)

def get_auth_token(cookie_str):
    """Stage 1: Mendapatkan MX dan IDX"""
    res = request_with_retry("https://siakad.uin-malang.ac.id/2.0/uin-krs", cookie_str=cookie_str)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, 'html.parser')
        mx_el = soup.find('input', {'id': 'mx'})
        idx_el = soup.find('input', {'id': 'idx'})
        if mx_el and idx_el:
            return mx_el['value'], idx_el['value']
    return None, None

def get_course_ids(jadwals, idx_value, cookie_str, log_placeholder):
    """Stage 2: Targeted Caching (Mencari ID Matkul)"""
    cached_ids = {}
    found_count = 0
    
    log_placeholder.info(f"🔎 Mencari ID untuk {len(jadwals)} mata kuliah...")
    
    # Loop pencarian (disederhanakan untuk web agar tidak infinite loop blocking UI terlalu lama)
    # Kita coba cari maksimal 5 kali putaran jika belum ketemu semua
    for attempt in range(1, 100): 
        if len(cached_ids) == len(jadwals):
            break

        response = request_with_retry(
            "https://siakad.uin-malang.ac.id/2.0/ajx", 
            method="POST", 
            data={'vw_mk': idx_value}, 
            cookie_str=cookie_str
        )
        
        if response.status_code == 200:
            srv_soup = BeautifulSoup(response.text, 'html.parser')
            rows = srv_soup.find_all('tr')
            
            for target in jadwals:
                t_m, t_h, t_j, t_d = target
                key = f"{t_m}|{t_d}"
                
                if key in cached_ids: continue
                
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) > 6:
                        srv_matkul = cols[2].get_text(strip=True).replace(" ","")
                        srv_dosen  = cols[4].get_text(strip=True).replace(" ","")
                        srv_hari   = cols[5].get_text(strip=True).replace(" ","")
                        srv_jam    = cols[6].get_text(strip=True).replace(" ","")

                        if (srv_matkul == t_m.replace(" ","") and 
                            srv_dosen  == t_d.replace(" ","") and
                            srv_hari   == t_h.replace(" ","") and
                            srv_jam    == t_j.replace(" ","")):
                            
                            a_tag = row.find('a', id=True)
                            if a_tag:
                                cached_ids[key] = a_tag['id']
                                log_placeholder.write(f"✅ Ditemukan: {t_m} (ID: {a_tag['id']})")
                                break
        
        time.sleep(1) # Jeda antar refresh pencarian ID
        
    return cached_ids

def war_worker(key, ad_kr, mx_value, cookie_str, status_container):
    """Stage 3: Worker Thread per Matkul"""
    name = key.split('|')[0]
    retry_count = 0
    
    # Loop sampai sukses
    while key not in st.session_state.success_list:
        try:
            # Request KRS
            res = request_with_retry(
                "https://siakad.uin-malang.ac.id/2.0/ajx", 
                method="POST", 
                data={"ad_kr": ad_kr, "mx": mx_value}, 
                cookie_str=cookie_str
            )
            
            toast = BeautifulSoup(res.text, 'html.parser').find('div', class_='toast-body')
            msg = toast.get_text(strip=True) if toast else "No Response"
            retry_count += 1
            
            # Update UI Container untuk baris ini
            if "sukses" in msg.lower():
                status_container.success(f"**{name}**: BERHASIL DIAMBIL! 🎉")
                st.session_state.success_list.add(key)
                break
            else:
                # Tampilkan status retry/gagal secara real-time
                if "penuh" in msg.lower():
                     status_container.error(f"**{name}**: {msg} (Retry {retry_count}x)")
                else:
                     status_container.warning(f"**{name}**: {msg} (Retry {retry_count}x)")
            
            time.sleep(0.01) # Jeda agresif
        except Exception as e:
            status_container.error(f"Error: {e}")
            time.sleep(0.5)

# --- UI LAYOUT ---

st.title("🚀 Auto KRS UIN Malang (Web Version)")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.header("1. Konfigurasi")
    cookie_input = st.text_input("Cookie (PHPSESSID)", placeholder="Paste cookie value only", type="password")
    
    st.info("Format Jadwal: Matkul|Hari|Jam|Dosen")
    default_jadwal = "Bahasa Inggris|Senin|07:00-09:30|Dr. Budi\nFisika Dasar|Selasa|09:30-12:00|Prof. Siti"
    jadwal_text = st.text_area("Jadwal Target (Satu per baris)", value=default_jadwal, height=200)
    
    start_btn = st.button("MULAI PERANG KRS 🔥", type="primary")

with col2:
    st.header("2. Status Eksekusi")
    log_area = st.empty()
    war_area = st.container()

# --- MAIN EXECUTION LOGIC ---

if start_btn:
    if not cookie_input or not jadwal_text:
        st.error("Cookie dan Jadwal harus diisi!")
    else:
        # Reset State
        st.session_state.success_list = set()
        
        # Parsing Jadwal
        jadwals = [line.strip().split('|') for line in jadwal_text.split('\n') if line.strip()]
        
        # STAGE 1: AUTH
        log_area.info("🔄 Menghubungkan ke SIAKAD...")
        mx, idx = get_auth_token(cookie_input)
        
        if not mx or not idx:
            log_area.error("❌ Gagal Login! Cek Cookie atau Server Down.")
        else:
            log_area.success(f"✅ Login Berhasil! (MX: {mx[:10]}... | IDX: {idx[:10]}...)")
            
            # STAGE 2: CACHING
            cached_ids = get_course_ids(jadwals, idx, cookie_input, log_area)
            
            if len(cached_ids) < len(jadwals):
                log_area.warning(f"⚠️ Hanya ditemukan {len(cached_ids)} dari {len(jadwals)} matkul. Lanjut perang...")
            else:
                log_area.success(f"✅ Semua {len(cached_ids)} ID Matkul ditemukan! Memulai Multi-threading...")
            
            # STAGE 3: WAR (MULTI-THREADING)
            with war_area:
                st.write("---")
                st.subheader(f"⚔️ War Zone ({len(cached_ids)} Threads)")
                
                # Buat container UI terpisah untuk setiap matkul agar bisa update sendiri-sendiri
                status_containers = {}
                for key in cached_ids:
                    name = key.split('|')[0]
                    col_status = st.empty()
                    col_status.info(f"⏳ Menyiapkan thread untuk: {name}...")
                    status_containers[key] = col_status
                
                # Jalankan Threads
                with ThreadPoolExecutor(max_workers=len(cached_ids)) as executor:
                    futures = []
                    for key, ad_kr in cached_ids.items():
                        # Pass container spesifik ke worker
                        futures.append(
                            executor.submit(war_worker, key, ad_kr, mx, cookie_input, status_containers[key])
                        )
                    
                    # Tunggu semua selesai (Blocking wait)
                    # Di streamlit web, user akan melihat update real-time via container
                    for future in futures:
                        future.result()
            
            # STAGE 4: RECAP
            st.success("🏁 SEMUA THREAD SELESAI!")
            res_f = request_with_retry("https://siakad.uin-malang.ac.id/2.0/uin-krs", cookie_str=cookie_input)
            sks_soup = BeautifulSoup(res_f.text, 'html.parser').find('td', {'id': 'jmlsks'})
            if sks_soup:
                st.metric(label="Total SKS Terambil", value=sks_soup.get_text(strip=True))
