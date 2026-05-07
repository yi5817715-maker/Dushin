import streamlit as st
import os
import subprocess
import time
import pandas as pd
import requests
from playwright.sync_api import sync_playwright

# ==========================================
# 1. 环境初始化（解决云端浏览器缺失问题）
# ==========================================
@st.cache_resource
def init_playwright():
    """在 Linux 云端环境下自动安装 Chromium 浏览器"""
    if os.name != 'nt':  # 如果不是 Windows 环境（即在 Streamlit Cloud 上）
        try:
            # 检查是否已安装
            playwright_path = os.path.expanduser("~/.cache/ms-playwright")
            if not os.path.exists(playwright_path):
                st.info("正在初始化云端浏览器环境，请稍候约 1-2 分钟...")
                # 安装 chromium 及其运行依赖
                subprocess.run(["playwright", "install", "chromium"], check=True)
                subprocess.run(["playwright", "install-deps"], check=True)
                st.success("浏览器环境配置成功！")
            return True
        except Exception as e:
            st.error(f"浏览器初始化失败: {e}")
            return False
    return True

# 执行初始化
init_playwright()

# ==========================================
# 2. 核心抓取逻辑
# ==========================================
def fetch_web_content_with_links(url):
    """使用 Playwright 抓取网页文字，适配云端与本地"""
    try:
        with sync_playwright() as p:
            # 配置启动参数，增加稳定性
            launch_kwargs = {
                "headless": True,
                "args": [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled'
                ]
            }
            
            # 如果是本地 Windows，尝试手动寻找 Chrome 路径
            if os.name == 'nt':
                potential_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
                ]
                for path in potential_paths:
                    if os.path.exists(path):
                        launch_kwargs["executable_path"] = path
                        break

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # 设置超时并访问
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)  # 等待动态内容加载
            
            # 提取正文并保留链接特征
            content = page.evaluate("""() => {
                const junk = ['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript'];
                junk.forEach(tag => document.querySelectorAll(tag).forEach(el => el.remove()));
                return document.body.innerText;
            }""")
            
            browser.close()
            return content[:10000] # 截取前1万字防止 Token 溢出
    except Exception as e:
        return f"抓取失败: {str(e)}"

# ==========================================
# 3. MiniMax AI 处理逻辑
# ==========================================
def analyze_with_minimax(content, api_key):
    """将抓取内容发送给 MiniMax 进行提炼"""
    url = "https://api.minimax.chat/v1/text/chatcompletion_v2"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "abab6.5s-chat", # 或者你使用的其他 MiniMax 模型
        "messages": [
            {"role": "system", "content": "你是一个资深的行业分析师，请从抓取的网页内容中提炼出关键动态、价格变动或竞品信息。"},
            {"role": "user", "content": f"请简要分析以下内容：\n\n{content}"}
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"AI 分析失败: {e}"

# ==========================================
# 4. Streamlit UI 界面
# ==========================================
st.set_page_config(page_title="🛡️ 竞争对手动态监测", layout="wide")
st.title("🛡️ 竞争对手动态监测系统")

# 从 Secrets 获取 API KEY
api_key = st.secrets.get("MINIMAX_API_KEY")

target_url = st.text_input("输入监测网址 (如竞品官网新闻页):", placeholder="https://example.com/news")

if st.button("开始监测"):
    if not api_key:
        st.error("请先在 Streamlit Secrets 中配置 MINIMAX_API_KEY")
    elif not target_url:
        st.warning("请输入网址")
    else:
        with st.spinner("🕵️ 正在潜入网页提取信息..."):
            web_text = fetch_web_content_with_links(target_url)
            
            if "抓取失败" in web_text:
                st.error(web_text)
            else:
                st.success("抓取成功！正在交给 AI 进行情报分析...")
                analysis = analyze_with_minimax(web_text, api_key)
                
                st.subheader("📋 情报分析报告")
                st.markdown(analysis)
                
                with st.expander("查看抓取原文"):
                    st.text(web_text)
