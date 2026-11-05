"""Construct per-application services and their shared runtime configuration."""
from dataclasses import dataclass, field
from comfyui_wrapper.models.model_families import validate_checkpoint_lora_folders
from pathlib import Path
from comfyui_wrapper.settings.app_config import validate_ollama_urls, validate_keep_alive, validate_analysis_model, validate_gallery_retention_days
from comfyui_wrapper.app_metadata import ANALYSIS_MODEL
from comfyui_wrapper.generation.generation_jobs import GenerationJobs
from comfyui_wrapper.models.model_catalog import ModelCatalog
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.generation.batch_generation import BatchStore
from comfyui_wrapper.gallery.gallery_cleanup import ExecutionCleanup
from comfyui_wrapper.gallery.gallery_thumbnails import ThumbnailCache
from comfyui_wrapper.gallery.storage_usage import StorageUsage
from comfyui_wrapper.settings.settings_presets import PresetStore
from comfyui_wrapper.models.lora_store import LoraStore
from comfyui_wrapper.settings.instruction_presets import InstructionStore

@dataclass(frozen=True)
class Runtime:
    root: Path
    ollama_url: str
    comfy_url: str
    wd_dir: Path | str | None
    checkpoint_families: dict | None
    lora_folders: dict | None
    ollama_urls: list
    ollama_keep_alive: int | str
    analysis_model: str = ANALYSIS_MODEL
    checkpoint_lora_folders: dict = field(default_factory=dict)
    gallery_retention_days: int = 10

@dataclass
class ApplicationServices:
    runtime: Runtime
    runner: GenerationJobs
    catalog: ModelCatalog
    history: HistoryStore
    batches: BatchStore
    storage: StorageUsage
    thumbnails: ThumbnailCache
    cleanup: ExecutionCleanup
    presets: PresetStore
    lora_store: LoraStore
    instructions: InstructionStore

def create_services(root, logger, *, ollama_url, comfy_url, wd_dir, checkpoint_families,
                    lora_folders, ollama_urls, ollama_keep_alive, analysis_model=ANALYSIS_MODEL, checkpoint_lora_folders=None, gallery_retention_days=10):
    runtime = Runtime(root, ollama_url, comfy_url, wd_dir, checkpoint_families, lora_folders,
        validate_ollama_urls(ollama_urls if ollama_urls is not None else []), validate_keep_alive(ollama_keep_alive), validate_analysis_model(analysis_model), validate_checkpoint_lora_folders({} if checkpoint_lora_folders is None else checkpoint_lora_folders), validate_gallery_retention_days(gallery_retention_days))
    history = HistoryStore(root/'history.sqlite3')
    storage = StorageUsage(root, history)
    runner = GenerationJobs(runtime, history, storage, logger)
    batches = BatchStore(history, root, runner.lock, runner.records)
    runner.batches = batches
    thumbnails = ThumbnailCache(root/'.gallery-thumbnails')
    cleanup = ExecutionCleanup(history, root, runner.lock, runner.records, thumbnails, retention_days=runtime.gallery_retention_days)
    return ApplicationServices(runtime, runner, ModelCatalog(runtime), history, batches, storage,
        thumbnails, cleanup, PresetStore(root/'settings-presets.sqlite3'), LoraStore(root/'lora-triggers.sqlite3'), InstructionStore(root/'instruction-presets.sqlite3'))
