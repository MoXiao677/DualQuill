"""设置边界：环境变量仅检查有无，不返回、存储或记录密钥正文。"""
import os

MODULE = {"id": "settings", "name": "设置与 API 密钥管理", "status": "partial", "description": "三个站点独立配置、Windows 账户加密保存、真实模型列表检查；文本生成仍未接入。"}


def safe_status() -> dict:
    return {
        "model_calls_enabled": False,
        "providers": {
            "deepseek": {"key_configured": bool(os.environ.get("DEEPSEEK_API_KEY"))},
            "gemini": {"key_configured": bool(os.environ.get("GEMINI_API_KEY"))},
        },
    }
