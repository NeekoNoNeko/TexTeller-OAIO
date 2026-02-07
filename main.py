from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Union, Optional, Dict, AsyncGenerator
import time
import base64
import io
import numpy as np
from PIL import Image
import configparser
import os
import json
import asyncio

# --- 1. 读取配置文件 ---
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
if not os.path.exists(config_path):
    config_path = 'config.ini'
config.read(config_path, encoding='utf-8')

API_KEY = config.get('auth', 'api_key').strip()
USE_ONNX = config.getboolean('model', 'use_onnx', fallback=False)

# --- 2. 加载 TexTeller 模型 ---
print(f"正在加载 TexTeller 模型 (使用 ONNX: {USE_ONNX})...")
from texteller import load_model, load_tokenizer, img2latex

model = load_model(use_onnx=USE_ONNX)
tokenizer = load_tokenizer()
print("模型加载完成！")

# --- 3. FastAPI 初始化 & CORS ---
app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 4. 请求体模型 ---
class ContentItem(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class Message(BaseModel):
    role: str
    content: Union[str, List[ContentItem]]


class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: Optional[bool] = False  # 关键：接收是否请求流式传输
    # 其他字段忽略
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None


# --- 5. 核心接口 ---
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    # --- A. 验证 API Key ---
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    client_token = auth_header.split(" ", 1)[1].strip()
    if client_token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    # --- B. 提取图片 ---
    image_base64 = None
    for msg in req.messages:
        if isinstance(msg.content, list):
            for item in msg.content:
                if item.type == "image_url" and item.image_url:
                    raw_url = item.image_url.get("url", "")
                    if "," in raw_url:
                        image_base64 = raw_url.split(",", 1)[1]
                        break
            if image_base64: break

    if not image_base64:
        # 简单的回退
        if isinstance(req.messages[0].content, str) and req.messages[0].content.startswith("data:"):
            raw_url = req.messages[0].content
            if "," in raw_url: image_base64 = raw_url.split(",", 1)[1]
        if not image_base64:
            raise HTTPException(status_code=400, detail="No image found in request.")

    # --- C. 推理识别 ---
    try:
        image_data = base64.b64decode(image_base64)
        pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
        img_array = np.array(pil_image)
        latex_results = img2latex(model, tokenizer, [img_array])
        latex_code = latex_results[0]

    except Exception as e:
        print(f"推理出错: {e}")
        raise HTTPException(status_code=500, detail=f"Inference failed: {str(e)}")

    # --- D. 构造响应数据结构 (符合 WriteTex 文档示例) ---
    response_data = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": latex_code,
                    "reasoning_content": ""  # WriteTex 文档里有的字段，加上更保险
                },
                "logprobs": None,
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

    # --- E. 根据请求决定返回格式 ---
    if req.stream:
        # 如果请求流式，返回 StreamingResponse
        async def generate_stream() -> AsyncGenerator[str, None]:
            # OpenAI 流式格式：data: {json}\n\n
            chunk = {
                "id": response_data["id"],
                "object": "chat.completion.chunk",
                "created": response_data["created"],
                "model": response_data["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": latex_code
                        },
                        "logprobs": None,
                        "finish_reason": None
                    }
                ]
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            # 发送结束标记
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate_stream(), media_type="text/event-stream")
    else:
        # 否则返回普通 JSON
        return response_data


@app.get("/")
async def read_root():
    return {"message": "TexTeller-OAIO is running (Final v1.0)"}