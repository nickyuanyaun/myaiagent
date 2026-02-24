import http.server
import socketserver
import webbrowser
import os
import urllib.parse
import json
import sys
# Added for model fetching
try:
    from google import genai
except ImportError:
    genai = None

# --- Configuration & Styling ---
PORT = 8080
ENV_FILE = ".env"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MyAIAgent - 配置中心</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --bg: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --text: #f8fafc;
            --text-dim: #94a3b8;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.15) 0px, transparent 50%);
            color: var(--text);
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            overflow: hidden;
        }

        .container {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 3rem;
            border-radius: 24px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            width: 100%;
            max-width: 500px;
            animation: fadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        h1 { font-weight: 600; font-size: 2rem; margin-bottom: 0.5rem; text-align: center; }
        p.subtitle { color: var(--text-dim); text-align: center; margin-bottom: 2.5rem; }

        .form-group { margin-bottom: 1.5rem; }
        label { display: block; font-size: 0.9rem; font-weight: 400; color: var(--text-dim); margin-bottom: 0.5rem; }
        
        input {
            width: 100%;
            padding: 12px 16px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: white;
            font-family: inherit;
            box-sizing: border-box;
            transition: all 0.3s ease;
        }

        input:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
        }

        button {
            width: 100%;
            padding: 14px;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 1rem;
        }

        button:hover { background: var(--primary-hover); transform: translateY(-1px); }
        button:active { transform: translateY(0); }

        .footer { text-align: center; margin-top: 2rem; font-size: 0.8rem; color: var(--text-dim); }
        .footer a { color: var(--primary); text-decoration: none; }
        
        .row { display: flex; gap: 10px; align-items: flex-end; }
        .row .form-group { margin-bottom: 0; flex: 1; }
        .row button { width: auto; margin-top: 0; padding: 12px 20px; font-size: 0.9rem; white-space: nowrap; }
        
        #model-select {
            width: 100%;
            padding: 12px 16px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: white;
            font-family: inherit;
            box-sizing: border-box;
            transition: all 0.3s ease;
            appearance: none;
            cursor: pointer;
        }
        #model-select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
        }
        .help-text { font-size: 0.8rem; color: var(--text-dim); margin-top: 5px; }

        details {
            margin-top: 2rem;
            margin-bottom: 2rem;
            background: rgba(15, 23, 42, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            overflow: hidden;
        }

        summary {
            padding: 1rem;
            cursor: pointer;
            font-weight: 600;
            color: var(--text-dim);
            user-select: none;
            transition: all 0.3s ease;
        }

        summary:hover {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text);
        }

        .details-content {
            padding: 1.5rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .advanced-group {
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px dashed rgba(255, 255, 255, 0.1);
        }

        .advanced-group:last-child {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>MyAIAgent</h1>
        <p class="subtitle">欢迎使用！请完成系统初始配置</p>
        
        <form action="/save" method="POST">
            <div class="form-group">
                <label>Telegram Bot Token (@BotFather)</label>
                <input type="password" name="TG_TOKEN" placeholder="例如: 123456789:ABCDEF..." value="__TG_TOKEN__" required>
            </div>
            
            <div class="form-group">
                <label>Google Gemini API Key</label>
                <div class="row">
                    <input type="password" id="api_key" name="GOOGLE_KEY" placeholder="您的 Gemini Pro API 密钥" value="__GOOGLE_KEY__" required>
                    <button type="button" onclick="fetchModels()">获取模型</button>
                </div>
            </div>

            <div class="form-group">
                <label>AI 原生模型选择 (需先填写 API Key)</label>
                <input type="text" id="model_input" name="GEMINI_MODEL" list="model_list" placeholder="选择或填写 (默认: gemini-2.5-flash)" value="__GEMINI_MODEL__">
                <datalist id="model_list">
                    <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                    <option value="gemini-2.5-pro">gemini-2.5-pro</option>
                    <option value="gemini-3-pro-preview">gemini-3-pro-preview</option>
                </datalist>
                <div class="help-text" id="model_status">此致模型将用于网页搜索、文本规划和翻译。</div>
            </div>
            
            <div class="form-group">
                <label>您的 Telegram User ID (管理员)</label>
                <input type="text" name="USER_ID" placeholder="例如: 8526935699" value="__USER_ID__" required>
            </div>

            <details>
                <summary>高级设置 (点击展开) - 覆盖默认全局模型/API</summary>
                <div class="details-content">
                    <p class="help-text" style="margin-bottom: 15px;">留空则使用上方的全局设置。</p>
                    
                    <div class="advanced-group">
                        <label>图像生成模型 (Image Model)</label>
                        <input type="text" name="IMAGE_MODEL_NAME" placeholder="如: gemini-3-pro-image-preview" value="__IMAGE_MODEL_NAME__">
                        <div style="height: 5px;"></div>
                        <input type="password" name="IMAGE_API_KEY" placeholder="专用 API Key (可选)" value="__IMAGE_API_KEY__">
                    </div>

                    <div class="advanced-group">
                        <label>视频生成模型 (Video Model)</label>
                        <input type="text" name="VIDEO_MODEL_NAME" placeholder="如: sora-v1, veo-2.0" value="__VIDEO_MODEL_NAME__">
                        <div style="height: 5px;"></div>
                        <input type="password" name="VIDEO_API_KEY" placeholder="专用 API Key (可选)" value="__VIDEO_API_KEY__">
                    </div>

                    <div class="advanced-group">
                        <label>语音合成模型 (TTS Model)</label>
                        <input type="text" name="TTS_MODEL_NAME" placeholder="如: eleven-turbo-v2" value="__TTS_MODEL_NAME__">
                        <div style="height: 5px;"></div>
                        <input type="password" name="TTS_API_KEY" placeholder="专用 API Key (可选)" value="__TTS_API_KEY__">
                    </div>

                    <div class="advanced-group">
                        <label>MeTube 服务地址</label>
                        <input type="text" name="METUBE_URL" placeholder="http://localhost:8081" value="__METUBE_URL__">
                    </div>

                    <div class="advanced-group">
                        <label>MeTube 本地/共享下载目录</label>
                        <input type="text" name="METUBE_DOWNLOAD_DIR" placeholder="如: \\\\192.168.1.28\\LaCie\\..." value="__METUBE_DOWNLOAD_DIR__">
                    </div>
                </div>
            </details>

            <button type="submit">保存并开启 AI 助手</button>
        </form>

        <div class="footer">
            Powered by Antigravity Agent • <a href="https://github.com/nickyuanyaun/myaiagent" target="_blank">View on GitHub</a>
        </div>
    </div>

    <script>
        async function fetchModels() {
            const apiKey = document.getElementById('api_key').value;
            const statusLabel = document.getElementById('model_status');
            const dataList = document.getElementById('model_list');
            
            if (!apiKey) {
                statusLabel.innerText = "❌ 请先输入 Google API Key";
                statusLabel.style.color = "#ef4444";
                return;
            }

            statusLabel.innerText = "⏳ 正在拉取可用模型列表...";
            statusLabel.style.color = "var(--text-dim)";
            
            try {
                const response = await fetch(`/api/models?key=${apiKey}`);
                if (!response.ok) throw new Error("API 请求失败");
                const data = await response.json();
                
                if (data.models && data.models.length > 0) {
                    dataList.innerHTML = ''; // Clear default options
                    data.models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model;
                        dataList.appendChild(option);
                    });
                    statusLabel.innerText = `✅ 成功拉取 ${data.models.length} 个模型！请在上方下拉框选择。`;
                    statusLabel.style.color = "#22c55e";
                } else if (data.error) {
                    throw new Error(data.error);
                }
            } catch (err) {
                statusLabel.innerText = `❌ 拉取失败: ${err.message}`;
                statusLabel.style.color = "#ef4444";
            }
        }
    </script>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>配置成功</title>
    <style>
        body { background: #0f172a; color: white; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .msg { text-align: center; padding: 40px; border-radius: 20px; background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255,255,255,0.1); }
        h1 { color: #22c55e; }
    </style>
</head>
<body>
    <div class="msg">
        <h1>✅ 配置成功！</h1>
        <p>您的 .env 文件已生成。设置服务器即将关闭。</p>
        <p>现在请回到终端运行: <b>python main.py</b></p>
    </div>
</body>
</html>
"""

class SetupHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # Read current values if .env exists
            env_data = {}
            if os.path.exists(ENV_FILE):
                with open(ENV_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            env_data[k] = v.strip().strip('"\'')
            
            html = HTML_TEMPLATE
            html = html.replace('__TG_TOKEN__', env_data.get('TELEGRAM_BOT_TOKEN', ''))
            html = html.replace('__GOOGLE_KEY__', env_data.get('GOOGLE_API_KEY', ''))
            html = html.replace('__GEMINI_MODEL__', env_data.get('GEMINI_MODEL_NAME', 'gemini-2.5-flash'))
            html = html.replace('__USER_ID__', env_data.get('ALLOWED_USER_IDS', ''))
            html = html.replace('__IMAGE_MODEL_NAME__', env_data.get('IMAGE_MODEL_NAME', ''))
            html = html.replace('__IMAGE_API_KEY__', env_data.get('IMAGE_API_KEY', ''))
            html = html.replace('__VIDEO_MODEL_NAME__', env_data.get('VIDEO_MODEL_NAME', ''))
            html = html.replace('__VIDEO_API_KEY__', env_data.get('VIDEO_API_KEY', ''))
            html = html.replace('__TTS_MODEL_NAME__', env_data.get('TTS_MODEL_NAME', ''))
            html = html.replace('__TTS_API_KEY__', env_data.get('TTS_API_KEY', ''))
            html = html.replace('__METUBE_URL__', env_data.get('METUBE_URL', 'http://localhost:8081'))
            html = html.replace('__METUBE_DOWNLOAD_DIR__', env_data.get('METUBE_DOWNLOAD_DIR', ''))

            self.wfile.write(html.encode('utf-8'))
        elif self.path.startswith('/api/models'):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            key = params.get('key', [''])[0]
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response_data = {"models": []}
            if genai and key:
                try:
                    client = genai.Client(api_key=key)
                    # Get models that support generateContent
                    models = client.models.list()
                    model_names = [m.name for m in models if "generateContent" in m.supported_actions]
                    
                    # Sort logic to prioritize preferred models at the top
                    preferred = ["gemini-3-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
                    sorted_models = []
                    for p in preferred:
                        matching = [name for name in model_names if p in name or name.endswith(p)]
                        if matching:
                            sorted_models.append(matching[0])
                    
                    # Add any remaining models not in preferred list
                    for m in model_names:
                        if m not in sorted_models and "gemini" in m:
                            sorted_models.append(m)
                            
                    response_data["models"] = sorted_models
                except Exception as e:
                    response_data["error"] = str(e)
            elif not genai:
                response_data["error"] = "google-genai sdk not installed."
            
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/save':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            # Simple extraction
            tg_token = params.get('TG_TOKEN', [''])[0]
            google_key = params.get('GOOGLE_KEY', [''])[0]
            user_id = params.get('USER_ID', [''])[0]
            gemini_model = params.get('GEMINI_MODEL', ['gemini-2.5-flash'])[0]

            # Advanced extraction
            image_model = params.get('IMAGE_MODEL_NAME', [''])[0]
            image_api = params.get('IMAGE_API_KEY', [''])[0]
            video_model = params.get('VIDEO_MODEL_NAME', [''])[0]
            video_api = params.get('VIDEO_API_KEY', [''])[0]
            tts_model = params.get('TTS_MODEL_NAME', [''])[0]
            tts_api = params.get('TTS_API_KEY', [''])[0]

            # Write .env file
            env_content = f"TELEGRAM_BOT_TOKEN={tg_token}\n"
            env_content += f"ALLOWED_USER_IDS={user_id}\n"
            env_content += f"GOOGLE_API_KEY={google_key}\n"
            env_content += f"GEMINI_MODEL_NAME={gemini_model}\n"
            
            if image_model: env_content += f"IMAGE_MODEL_NAME={image_model}\n"
            if image_api: env_content += f"IMAGE_API_KEY={image_api}\n"
            if video_model: env_content += f"VIDEO_MODEL_NAME={video_model}\n"
            if video_api: env_content += f"VIDEO_API_KEY={video_api}\n"
            if tts_model: env_content += f"TTS_MODEL_NAME={tts_model}\n"
            if tts_api: env_content += f"TTS_API_KEY={tts_api}\n"

            metube_url = params.get('METUBE_URL', ['http://localhost:8081'])[0]
            if not metube_url: metube_url = "http://localhost:8081"
            env_content += f"METUBE_URL={metube_url}\n"
            
            metube_dir = params.get('METUBE_DOWNLOAD_DIR', [''])[0]
            if metube_dir: env_content += f"METUBE_DOWNLOAD_DIR={metube_dir}\n"

            env_content += "WP_URL=https://your-wordpress-site.com\n"
            env_content += "WP_USER=admin\n"
            env_content += "WP_PASSWORD=your_app_password\n"

            with open(ENV_FILE, 'w', encoding='utf-8') as f:
                f.write(env_content)

            # Response
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(SUCCESS_HTML.encode('utf-8'))
            
            print("\\n[!] .env file saved. Shutting down setup server...")
            # Schedule shutdown
            sys.exit(0)

def run_server():
    with socketserver.TCPServer(("", PORT), SetupHandler) as httpd:
        print(f"[*] Configuration server running at http://localhost:{PORT}")
        print("[*] Opening browser...")
        webbrowser.open(f"http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except SystemExit:
            pass

if __name__ == "__main__":
    run_server()
