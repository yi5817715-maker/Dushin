import streamlit as st
import pandas as pd
import time
import requests
import json
import os
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

st.set_page_config(page_title="竞争对手监测站", layout="wide")

# 注入简单 CSS 让“停止按钮”更醒目（变红）
st.markdown("""
    <style>
    div[data-testid="stButton"] button[kind="secondary"] {
        border-color: #ff4b4b;
        color: #ff4b4b;
    }
    div[data-testid="stButton"] button[kind="secondary"]:hover {
        background-color: #ff4b4b;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# --- 配置区 ---
MINIMAX_API_KEY = "sk-cp-lqDcalhJl1FcDrT6Rbbbaq9-Ie-8JN2dDhF4rihurHS2a6DDGPB4mJB-SU0avNPzW7-29IjNFDRyNIH8UK8-vwWGMwT8bPOJqha0PV5Ma8PWg0PbmbMDGWQ"

st.title("🛡️ 竞争对手动态监测系统")

# --- 1. 状态管理初始化 ---
if 'running' not in st.session_state:
    st.session_state.running = False

if 'target_list' not in st.session_state:
    st.session_state.target_list = pd.DataFrame([
        {"网站名称": "中国制造网最新活动", "URL": "https://service.made-in-china.com/"},
        {"网站名称": "阿里巴巴国际站规则", "URL": "https://rulechannel.alibaba.com/icbu#/"}
    ])

if 'scan_results' not in st.session_state:
    st.session_state.scan_results = {}

# --- 2. 核心辅助函数 ---

def get_chrome_path():
    """兼容性路径获取：云端返回 None，让 Playwright 自动处理"""
    if os.name == 'nt':  # 只有在 Windows 本地才去搜寻路径
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
        ]
        for path in paths:
            if os.path.exists(path): return path
    return None # Linux 云端返回 None

def fetch_web_content_with_links(url):
    """增强版抓取：自动适配云端环境"""
    try:
        with sync_playwright() as p:
            # 配置启动参数
            launch_kwargs = {
                "headless": True,
                "args": [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox', # 云端必须
                    '--disable-infobars'
                ]
            }
            
            # 只有在 Windows 环境下手动指定 executable_path
            chrome_path = get_chrome_path()
            if chrome_path and os.name == 'nt':
                launch_kwargs["executable_path"] = chrome_path

            # 启动浏览器
            browser = p.chromium.launch(**launch_kwargs)
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            
            page = context.new_page()
            # 抹除自动化特征
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            # 访问页面
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except:
                page.goto(url, wait_until="load", timeout=30000)
            
            time.sleep(3)
            
            # 提取内容
            content = page.evaluate("""() => {
                const junk = ['script', 'style', 'nav', 'footer', 'header', 'iframe'];
                junk.forEach(tag => document.querySelectorAll(tag).forEach(el => el.remove()));
                document.querySelectorAll('a').forEach(a => {
                    if(a.href && a.href.startsWith('http')) {
                        const span = document.createElement('span');
                        span.innerText = ` [LINK:${a.href}] `;
                        a.appendChild(span);
                    }
                });
                return document.body.innerText;
            }""")
            
            browser.close()
            return content[:10000]
            
    except Exception as e:
        return f"抓取失败: {str(e)[:150]}"

def analyze_with_minimax(site_name, content, date_limit):
    """MiniMax 分析核心函数"""
    api_url = "https://api.minimaxi.com/v1/chat/completions"
    prompt = f"你是一个情报专家。提炼 {site_name} 在 {date_limit} 后的5条动态。必须提供 [LINK:网址] 中的原文链接。JSON格式：[{{\"标题\":\"\",\"描述\":\"\",\"原文链接\":\"\"}}]\n内容：{content}"
    
    payload = {
        "model": "MiniMax-M2.7", 
        "messages": [{"role": "system", "content": "你只输出JSON数组。"}, {"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        raw_content = response.json()['choices'][0]['message']['content'].strip()
        json_match = re.search(r'\[\s*\{.*\}\s*\]', raw_content, re.DOTALL)
        return json.loads(json_match.group()) if json_match else []
    except:
        return []

# --- 3. 监测配置 ---
st.subheader("⚙️ 监测配置")
col_cfg1, col_cfg2 = st.columns([2, 1])

with col_cfg1:
    time_range = st.select_slider(
        "选择监测信息的时间范围：",
        options=["近7天", "近30天", "近90天"],
        value="近7天",
        disabled=st.session_state.running 
    )

with col_cfg2:
    days_map = {"近7天": 7, "近30天": 30, "近90天": 90}
    search_date_limit = (datetime.now() - timedelta(days=days_map[time_range])).strftime('%Y-%m-%d')
    st.info(f"📅 提取 **{search_date_limit}** 之后的动态")

# --- 4. 名单管理 ---
st.subheader("📋 监测名单管理")
edited_df = st.data_editor(
    st.session_state.target_list,
    num_rows="dynamic",
    use_container_width=True,
    disabled=st.session_state.running,
    key="site_editor_v8"
)

# --- 5. 控制按钮 ---
st.markdown("---")
col_btn1, col_btn2 = st.columns([1, 1])

if col_btn1.button("🚀 启动监测", type="primary", use_container_width=True, disabled=st.session_state.running):
    st.session_state.running = True
    st.rerun()

if col_btn2.button("🛑 停止分析", type="secondary", use_container_width=True, disabled=not st.session_state.running):
    st.session_state.running = False
    st.rerun()

# --- 6. 执行监测逻辑 ---
if st.session_state.running:
    active_tasks = edited_df.dropna(subset=['网站名称', 'URL'])
    
    if active_tasks.empty:
        st.error("❌ 监测列表为空。")
        st.session_state.running = False
        st.rerun()
    else:
        status_area = st.empty()
        progress_bar = st.progress(0)
        
        for index, (_, row) in enumerate(active_tasks.iterrows()):
            if not st.session_state.running:
                break
                
            name, target_url = str(row['网站名称']), row['URL']
            with status_area.container():
                st.info(f"⏳ 正在分析: **{name}**")
                raw_text = fetch_web_content_with_links(target_url)
                
                if "抓取失败" not in raw_text:
                    results = analyze_with_minimax(name, raw_text, search_date_limit)
                    # 调试语句放在执行逻辑中，而不是函数定义中
                    st.write(f"✅ {name}: 成功提取 {len(results)} 条结果")
                    st.session_state.scan_results[name] = results
                else:
                    st.session_state.scan_results[name] = [{"标题": "抓取失败", "描述": raw_text, "原文链接": target_url}]
            
            progress_bar.progress((index + 1) / len(active_tasks))
        
        st.session_state.running = False
        st.session_state.target_list = edited_df
        st.rerun()

# --- 7. 结果展示 ---
st.subheader("📑 情报展示")
scanned_names = list(st.session_state.scan_results.keys())

if scanned_names:
    tabs = st.tabs(scanned_names)
    for i, tab in enumerate(tabs):
        with tab:
            name = scanned_names[i]
            results = st.session_state.scan_results.get(name, [])
            for item in results:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"### {item.get('标题', '未命名')}")
                    url = item.get('原文链接', '')
                    if url and str(url).startswith('http'):
                        c2.link_button("🔗 查看原文", url, use_container_width=True)
                    st.write(item.get('描述', '无描述内容'))
else:
    st.info("💡 尚未执行监测，请点击启动按钮。")
