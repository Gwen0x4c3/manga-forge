from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ModelPresetInfo:
    id: str
    label: str
    context_window: int | None = None
    supports_vision: bool = False
    supports_tools: bool = True
    supports_image_gen: bool = False
    supports_embedding: bool = False


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    name: str
    category: str  # aggregator | global | china | image | custom
    interface_type: str  # openai_compatible | gemini_image | comfyui | antigravity | mock
    base_url: str
    default_model: str
    description: str
    requires_api_key: bool = True
    supports_llm: bool = True
    supports_vision: bool = True
    supports_image: bool = False
    supports_embedding: bool = False
    api_key_placeholder: str = "sk-..."
    docs_url: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    models: tuple[ModelPresetInfo, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["models"] = [asdict(m) for m in self.models]
        return d


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="openrouter",
        name="OpenRouter",
        category="aggregator",
        interface_type="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-sonnet-4.5",
        description="统一聚合 OpenAI / Claude / Gemini / GLM / DeepSeek / Kimi，一个 Key 畅用全网模型。",
        supports_llm=True,
        supports_vision=True,
        supports_image=False,
        supports_embedding=False,
        api_key_placeholder="sk-or-v1-...",
        docs_url="https://openrouter.ai/keys",
        extra_headers={"HTTP-Referer": "https://github.com/Gwen0x4c3/manga-forge", "X-Title": "MangaForge"},
        models=(
            ModelPresetInfo("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", 200000, True, True),
            ModelPresetInfo("openai/gpt-4.1", "GPT-4.1", 1047576, True, True),
            ModelPresetInfo("google/gemini-2.5-pro", "Gemini 2.5 Pro", 1048576, True, True),
            ModelPresetInfo("google/gemini-2.5-flash", "Gemini 2.5 Flash", 1048576, True, True),
            ModelPresetInfo("deepseek/deepseek-chat-v3-0324", "DeepSeek V3", 163840, False, True),
            ModelPresetInfo("moonshotai/kimi-k2.5", "Kimi K2.5", 262144, True, True),
            ModelPresetInfo("z-ai/glm-4.5", "GLM-4.5", 131072, False, True),
        ),
    ),
    ProviderPreset(
        key="openai",
        name="OpenAI (GPT)",
        category="global",
        interface_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1",
        description="OpenAI 官方接口，同时支持 GPT 推理、识图、GPT-Image 作图与 Embedding 向量化。",
        supports_llm=True,
        supports_vision=True,
        supports_image=True,
        supports_embedding=True,
        api_key_placeholder="sk-proj-...",
        docs_url="https://platform.openai.com/api-keys",
        models=(
            ModelPresetInfo("gpt-4.1", "GPT-4.1", 1047576, True, True),
            ModelPresetInfo("gpt-4o", "GPT-4o", 128000, True, True),
            ModelPresetInfo("gpt-4.1-mini", "GPT-4.1 Mini", 1047576, True, True),
            ModelPresetInfo("gpt-image-2", "GPT Image 2 (作图)", None, False, False, True, False),
            ModelPresetInfo("gpt-image-1", "GPT Image 1 (作图)", None, False, False, True, False),
            ModelPresetInfo("text-embedding-3-small", "Embedding 3 Small", 8191, False, False, False, True),
        ),
    ),
    ProviderPreset(
        key="anthropic",
        name="Anthropic (Claude)",
        category="global",
        interface_type="openai_compatible",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-5-20250929",
        description="Anthropic 官方 OpenAI 兼容端点，直接填入 sk-ant Key 即可使用 Claude 长上下文编剧与识图。",
        supports_llm=True,
        supports_vision=True,
        supports_image=False,
        supports_embedding=False,
        api_key_placeholder="sk-ant-...",
        docs_url="https://console.anthropic.com/settings/keys",
        models=(
            ModelPresetInfo("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5", 200000, True, True),
            ModelPresetInfo("claude-opus-4-1-20250805", "Claude Opus 4.1", 200000, True, True),
            ModelPresetInfo("claude-haiku-4-5-20251001", "Claude Haiku 4.5", 200000, True, True),
        ),
    ),
    ProviderPreset(
        key="gemini",
        name="Google Gemini",
        category="global",
        interface_type="openai_compatible",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-pro",
        description="Google Gemini 官方端点，支持百万级上下文、多模态漫画识图与 Nano Banana 角色一致生图。",
        supports_llm=True,
        supports_vision=True,
        supports_image=True,
        supports_embedding=True,
        api_key_placeholder="AIza...",
        docs_url="https://aistudio.google.com/apikey",
        models=(
            ModelPresetInfo("gemini-2.5-pro", "Gemini 2.5 Pro", 1048576, True, True),
            ModelPresetInfo("gemini-2.5-flash", "Gemini 2.5 Flash", 1048576, True, True),
            ModelPresetInfo("gemini-3.1-flash-image", "Nano Banana 2 (作图)", None, False, False, True, False),
            ModelPresetInfo("gemini-3-pro-image", "Nano Banana Pro (作图)", None, False, False, True, False),
            ModelPresetInfo("text-embedding-004", "Gemini Embedding 004", 2048, False, False, False, True),
        ),
    ),
    ProviderPreset(
        key="glm_coding",
        name="智谱 GLM Coding Plan",
        category="china",
        interface_type="openai_compatible",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        default_model="glm-5.4",
        description="智谱 Coding Plan 套餐专属端点，填入 API Key 即可开箱即用，支持长上下文与多模态识图。",
        supports_llm=True,
        supports_vision=True,
        supports_image=False,
        supports_embedding=False,
        api_key_placeholder="填入智谱 Coding Plan API Key",
        docs_url="https://open.bigmodel.cn/usercenter/apikeys",
        models=(
            ModelPresetInfo("glm-5.4", "GLM-5.4 (识图+深度思考)", 1000000, True, True),
            ModelPresetInfo("glm-5.3-flash", "GLM-5.3-Flash (高速)", 1000000, True, True),
            ModelPresetInfo("glm-4.7", "GLM-4.7", 200000, True, True),
        ),
    ),
    ProviderPreset(
        key="glm",
        name="智谱 GLM（按量 API）",
        category="china",
        interface_type="openai_compatible",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.3-flash",
        description="智谱开放平台标准端点，支持 GLM 文本/识图、CogView 作图与 Embedding-3。",
        supports_llm=True,
        supports_vision=True,
        supports_image=True,
        supports_embedding=True,
        api_key_placeholder="填入智谱开放平台 API Key",
        docs_url="https://open.bigmodel.cn/usercenter/apikeys",
        models=(
            ModelPresetInfo("glm-5.4", "GLM-5.4", 1000000, True, True),
            ModelPresetInfo("glm-5.3-flash", "GLM-5.3-Flash", 1000000, True, True),
            ModelPresetInfo("glm-4.6v", "GLM-4.6V (视觉)", 128000, True, True),
            ModelPresetInfo("cogview-4-250304", "CogView-4 (作图)", None, False, False, True, False),
            ModelPresetInfo("embedding-3", "Embedding-3", 8192, False, False, False, True),
        ),
    ),
    ProviderPreset(
        key="kimi",
        name="Kimi (Moonshot)",
        category="china",
        interface_type="openai_compatible",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.5",
        description="月之暗面 Kimi 官方 API，中文对话细腻，适合长篇漫画编剧与台词润色。",
        supports_llm=True,
        supports_vision=True,
        supports_image=False,
        supports_embedding=False,
        api_key_placeholder="sk-...",
        docs_url="https://platform.moonshot.cn/console/api-keys",
        models=(
            ModelPresetInfo("kimi-k2.5", "Kimi K2.5 (多模态)", 262144, True, True),
            ModelPresetInfo("kimi-k3.1-pro", "Kimi K3.1 Pro", 1048576, True, True),
            ModelPresetInfo("kimi-k2-0905-preview", "Kimi K2 Preview", 262144, False, True),
            ModelPresetInfo("moonshot-v1-128k", "Moonshot V1 128K", 128000, False, True),
        ),
    ),
    ProviderPreset(
        key="deepseek",
        name="DeepSeek",
        category="china",
        interface_type="openai_compatible",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        description="DeepSeek 官方接口，自带高命中率硬盘 Prompt 缓存与极高性价比（纯文本编剧/审校推荐）。",
        supports_llm=True,
        supports_vision=False,
        supports_image=False,
        supports_embedding=False,
        api_key_placeholder="sk-...",
        docs_url="https://platform.deepseek.com/api_keys",
        models=(
            ModelPresetInfo("deepseek-chat", "DeepSeek Chat", 128000, False, True),
            ModelPresetInfo("deepseek-reasoner", "DeepSeek Reasoner", 128000, False, True),
            ModelPresetInfo("deepseek-flash", "DeepSeek Flash", 1048576, False, True),
        ),
    ),
    ProviderPreset(
        key="qwen",
        name="通义千问 (DashScope)",
        category="china",
        interface_type="openai_compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        description="阿里云百炼兼容模式端点，覆盖 Qwen-Max / Qwen-VL 漫画识图与向量模型。",
        supports_llm=True,
        supports_vision=True,
        supports_image=False,
        supports_embedding=True,
        api_key_placeholder="sk-...",
        docs_url="https://bailian.console.aliyun.com/",
        models=(
            ModelPresetInfo("qwen-plus", "Qwen-Plus", 1000000, False, True),
            ModelPresetInfo("qwen-max", "Qwen-Max", 128000, False, True),
            ModelPresetInfo("qwen-vl-max", "Qwen-VL-Max (识图)", 128000, True, True),
            ModelPresetInfo("text-embedding-v3", "Text Embedding V3", 8192, False, False, False, True),
        ),
    ),
    ProviderPreset(
        key="comfyui",
        name="ComfyUI（本地作图工作流）",
        category="image",
        interface_type="comfyui",
        base_url="http://localhost:8188",
        default_model="flux1-dev.safetensors",
        description="连接本地或局域网 ComfyUI 服务，挂载自定义 Checkpoint / LoRA 工作流渲染漫画分格。",
        requires_api_key=False,
        supports_llm=False,
        supports_vision=False,
        supports_image=True,
        supports_embedding=False,
        api_key_placeholder="本地服务无需 API Key（可留空）",
        models=(
            ModelPresetInfo("flux1-dev.safetensors", "Flux.1 Dev", None, False, False, True, False),
            ModelPresetInfo("animagine-xl-4.0.safetensors", "Animagine XL 4.0", None, False, False, True, False),
        ),
    ),
    ProviderPreset(
        key="custom",
        name="自定义 OpenAI 兼容服务",
        category="custom",
        interface_type="openai_compatible",
        base_url="",
        default_model="",
        description="接入任意 OneAPI / NewAPI 中转站、Ollama / vLLM / LM Studio 本地服务或企业私有网关。",
        requires_api_key=False,
        supports_llm=True,
        supports_vision=True,
        supports_image=True,
        supports_embedding=True,
        api_key_placeholder="如网关需要鉴权请填写 API Key",
        models=(),
    ),
)

PRESET_BY_KEY: dict[str, ProviderPreset] = {p.key: p for p in PROVIDER_PRESETS}
