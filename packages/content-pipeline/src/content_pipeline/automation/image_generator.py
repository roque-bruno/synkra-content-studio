"""
fal.ai Image Generator — NB2 SEMPRE como padrão.

NB2 é o padrão para TODA geração de imagem (com ou sem produto):
- Com produto: NB2 /edit (PNG do produto + prompt → produto no cenário)
- Sem produto: NB2 /edit prompt-only (datas comemorativas, institucional)
FLUX existe apenas como fallback de emergência se NB2 falhar.

Custo: ~$0.08/imagem (NB2), ~$0.04/imagem (FLUX dev fallback)
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image as PILImage

logger = logging.getLogger(__name__)


def _snap_to_64(value: int) -> int:
    """Arredonda para o múltiplo de 64 mais próximo (mínimo 64). fal.ai exige isso."""
    return max(64, round(value / 64) * 64)

COST_NB2 = 0.08
COST_FLUX_DEV = 0.04
COST_FLUX_PRO = 0.08

def _get_dimension_presets() -> dict:
    """Carrega dimension presets do image-generation-config.yaml via auto_prompt."""
    try:
        from content_pipeline.automation.auto_prompt import _load_image_gen_config
        cfg = _load_image_gen_config()
        presets_raw = cfg.get("dimension_presets", {})
        # Converter listas [w,h] para tuplas (w,h)
        return {k: tuple(v) if isinstance(v, list) else v for k, v in presets_raw.items()}
    except Exception:
        return {
            "feed": (1080, 1350), "square": (1080, 1080),
            "stories": (1080, 1920), "landscape": (1920, 1080), "banner": (2560, 720),
        }


def _get_product_top_picks() -> dict:
    """Carrega product top picks do image-generation-config.yaml via auto_prompt."""
    try:
        from content_pipeline.automation.auto_prompt import _load_image_gen_config
        return _load_image_gen_config().get("product_top_picks", {})
    except Exception:
        return {}


@dataclass
class ImageResult:
    """Resultado de uma geracao de imagem."""
    success: bool
    image_url: str = ""
    image_path: str = ""
    width: int = 0
    height: int = 0
    cost_usd: float = 0
    elapsed_seconds: float = 0
    request_id: str = ""
    seed: int = 0
    error: str = ""
    model_used: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "image_url": self.image_url,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "request_id": self.request_id,
            "seed": self.seed,
            "error": self.error,
            "model_used": self.model_used,
        }


def resolve_product_image(product: str, product_images_dir: Path) -> Optional[Path]:
    """Resolve nome do produto → caminho do PNG TOP PICK."""
    key = product.strip().lower()
    logger.debug("resolve_product_image: key=%r dir=%s exists=%s", key, product_images_dir, product_images_dir.exists())
    # Tenta match direto
    rel = _get_product_top_picks().get(key)
    if rel:
        full = product_images_dir / rel
        logger.debug("resolve_product_image: direct match %s exists=%s", full, full.exists())
        if full.exists():
            return full
    # Tenta match parcial (ex: "LEV 4LEV" contém "lev")
    for k, v in _get_product_top_picks().items():
        if k in key or key in k:
            full = product_images_dir / v
            if full.exists():
                return full
    # Busca recursiva por nome
    if product_images_dir.exists():
        for img in product_images_dir.rglob("*.png"):
            if key in img.stem.lower():
                return img
    logger.warning("resolve_product_image: NO match for '%s' in %s", key, product_images_dir)
    return None


class FalImageGenerator:
    """Cliente para geração de imagens via fal.ai — NB2 como padrão, FLUX como fallback."""

    BASE_URL = "https://fal.run"

    MODELS = {
        # NB2 — padrão para tudo
        "nb2": "fal-ai/nano-banana-2/edit",          # NB2 v2 edit (com ou sem produto)
        "nb2-generate": "fal-ai/nano-banana-2",       # NB2 v2 text-to-image puro
        "nb2-pro": "fal-ai/nano-banana-pro/edit",     # NB2 Pro (melhor qualidade, $0.15)
        "nb1": "fal-ai/nano-banana",                   # NB1 original ($0.039)
        # FLUX — fallback apenas
        "flux-dev": "fal-ai/flux/dev",
        "flux-pro": "fal-ai/flux-pro/v1.1",
        "flux-schnell": "fal-ai/flux/schnell",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
        product_images_dir: Optional[Path] = None,
        base_url: str = "",
        budget_tracker: Optional[object] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("FAL_API_KEY", "")
        self.output_dir = output_dir or Path("output/generated")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.product_images_dir = product_images_dir or Path("docs_user/imagem_produtos")
        self.base_url = base_url  # ex: "https://studio.salkmedical.com"
        self.budget_tracker = budget_tracker
        self._fal_cdn_cache: dict[str, str] = {}  # file_path → fal CDN URL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_dimensions(self, format_preset: str = "", width: int = 0, height: int = 0) -> tuple[int, int]:
        """Resolve dimensões finais (target exato, sem snap)."""
        if format_preset and format_preset in _get_dimension_presets():
            return _get_dimension_presets()[format_preset]
        return (width or 1080, height or 1350)

    @staticmethod
    def _get_api_dimensions(w: int, h: int) -> tuple[int, int]:
        """Snap para múltiplo de 64 (exigência fal.ai/diffusion models)."""
        return (_snap_to_64(w), _snap_to_64(h))

    async def _upload_to_fal_cdn(self, file_path: Path) -> Optional[str]:
        """Upload local file to fal.ai CDN storage, return public URL. Cached."""
        cache_key = str(file_path)
        if cache_key in self._fal_cdn_cache:
            return self._fal_cdn_cache[cache_key]
        try:
            file_bytes = file_path.read_bytes()
            async with httpx.AsyncClient(timeout=60) as client:
                # fal.ai storage upload: initiate → PUT bytes
                init_resp = await client.post(
                    "https://rest.alpha.fal.ai/storage/upload/initiate",
                    headers={"Authorization": f"Key {self.api_key}"},
                    json={"content_type": "image/png", "file_name": file_path.name},
                )
                init_resp.raise_for_status()
                init_data = init_resp.json()
                upload_url = init_data["upload_url"]
                file_url = init_data["file_url"]
                # Upload raw bytes
                put_resp = await client.put(
                    upload_url,
                    content=file_bytes,
                    headers={"Content-Type": "image/png"},
                )
                put_resp.raise_for_status()
            self._fal_cdn_cache[cache_key] = file_url
            logger.info("Uploaded product PNG to fal CDN: %s → %s", file_path.name, file_url)
            return file_url
        except Exception as e:
            logger.warning("fal CDN upload failed (%s), falling back to self-referencing URL: %s", file_path.name, e)
            return None

    async def _get_product_image_url(self, product: str) -> Optional[str]:
        """Resolve produto → URL acessível para fal.ai (CDN upload preferred)."""
        img_path = resolve_product_image(product, self.product_images_dir)
        if not img_path:
            logger.warning("Product '%s': no local PNG found in %s", product, self.product_images_dir)
            return None
        # Preferir upload direto para fal CDN (mais confiável que URL do nosso server)
        fal_url = await self._upload_to_fal_cdn(img_path)
        if fal_url:
            return fal_url
        # Fallback: URL do nosso servidor (requer que fal.ai consiga acessar)
        rel = img_path.relative_to(self.product_images_dir)
        parts = list(rel.parts)
        url_path = "/assets/produtos/" + "/".join(urllib.parse.quote(p) for p in parts)
        if self.base_url:
            return self.base_url.rstrip("/") + url_path
        return url_path

    async def generate_nb2(
        self,
        prompt: str,
        product: str = "",
        product_image_url: str = "",
        negative_prompt: str = "",
        width: int = 1080,
        height: int = 1350,
        format_preset: str = "",
    ) -> ImageResult:
        """Gera imagem NB2 — sempre NB2, dois endpoints:
        - Com produto: /edit (image_urls obrigatório)
        - Sem produto: /generate (prompt-only, text-to-image)
        """
        if not self.configured:
            return ImageResult(success=False, error="FAL_API_KEY não configurada")

        # Resolver URL da imagem do produto
        img_url = product_image_url or (await self._get_product_image_url(product) if product else None)

        start = time.time()
        w, h = self._get_dimensions(format_preset, width, height)
        # Snap para múltiplo de 64 para a API (fal.ai exige)
        api_w, api_h = self._get_api_dimensions(w, h)

        # /edit exige image_urls — sem produto usa /generate (text-to-image)
        if img_url:
            model_id = self.MODELS["nb2"]  # fal-ai/nano-banana-2/edit
        else:
            model_id = self.MODELS["nb2-generate"]  # fal-ai/nano-banana-2
            logger.info("NB2 prompt-only mode (no product image) — usando endpoint generate")

        # NB2 (Google Gemini Imagen) usa aspect_ratio, NAO image_size.
        # Aspect ratios suportados: "1:1", "3:4", "4:3", "9:16", "16:9"
        # Instagram feed 1080x1350 = 4:5, mais proximo suportado = 3:4 (0.75 vs 0.8)
        def _aspect_for(w_: int, h_: int) -> str:
            ratio = w_ / h_
            # Mapeia para o aspect ratio suportado mais proximo
            candidates = {
                "1:1": 1.0,
                "3:4": 0.75,
                "4:3": 4/3,
                "9:16": 9/16,
                "16:9": 16/9,
            }
            return min(candidates.items(), key=lambda kv: abs(kv[1] - ratio))[0]

        aspect_ratio = _aspect_for(w, h)

        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "num_images": 1,
        }
        if img_url:
            payload["image_urls"] = [img_url]
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            logger.info("NB2 generating: %s | product=%s | target=%dx%d aspect=%s", model_id, product, w, h, aspect_ratio)
            logger.info("NB2 product URL: %s", img_url)

            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/{model_id}",
                    headers={
                        "Authorization": f"Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                result_data = resp.json()

            images = result_data.get("images", [])
            if not images:
                # NB2 pode retornar "image" ao invés de "images"
                single = result_data.get("image")
                if single:
                    images = [single] if isinstance(single, dict) else [{"url": single}]

            if not images:
                return ImageResult(success=False, error="NB2 não retornou imagem", model_used="nb2")

            image_info = images[0]
            image_url = image_info.get("url", "") if isinstance(image_info, dict) else str(image_info)
            request_id = str(int(time.time() * 1000))
            image_path = await self._download(image_url, request_id, target_size=(w, h))

            elapsed = time.time() - start

            if self.budget_tracker:
                try:
                    self.budget_tracker.record("nb2", COST_NB2, {"model": "nano-banana-2", "product": product})
                except Exception:
                    pass

            logger.info("NB2 gerada: %s (%.1fs, $%.4f, produto=%s)", image_path.name, elapsed, COST_NB2, product)

            return ImageResult(
                success=True,
                image_url=image_url,
                image_path=str(image_path),
                width=image_info.get("width", w) if isinstance(image_info, dict) else w,
                height=image_info.get("height", h) if isinstance(image_info, dict) else h,
                cost_usd=COST_NB2,
                elapsed_seconds=elapsed,
                request_id=request_id,
                seed=result_data.get("seed", 0),
                model_used="nb2",
            )

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                pass
            logger.error("NB2 HTTP error: %s — %s", e, error_body)
            return ImageResult(
                success=False,
                error=f"NB2 error {e.response.status_code}: {error_body or str(e)}",
                elapsed_seconds=time.time() - start,
                model_used="nb2",
            )
        except Exception as e:
            logger.error("NB2 erro: %s", e, exc_info=True)
            return ImageResult(success=False, error=str(e), elapsed_seconds=time.time() - start, model_used="nb2")

    async def generate_image(
        self,
        prompt: str,
        width: int = 1080,
        height: int = 1350,
        negative_prompt: str = "",
        model: str = "nb2",
        format_preset: str = "",
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: Optional[int] = None,
        product: str = "",
        product_image_url: str = "",
    ) -> ImageResult:
        """Gera imagem. NB2 SEMPRE como padrão (com ou sem produto). FLUX só como fallback.

        NB2 funciona em dois modos:
        - Com produto: image-to-image (PNG do produto + prompt)
        - Sem produto: prompt-only (datas comemorativas, institucional)
        """
        # NB2 é sempre o padrão
        result = await self.generate_nb2(
            prompt=prompt,
            product=product,
            product_image_url=product_image_url,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            format_preset=format_preset,
        )
        if result.success:
            return result
        # NB2 falhou — fallback para FLUX
        logger.warning("NB2 falhou (%s), tentando FLUX fallback", result.error)
        return await self.generate_flux_fallback(
            prompt=prompt,
            negative_prompt=negative_prompt,
            model=model,
            width=width,
            height=height,
            format_preset=format_preset,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
        )

    async def generate_flux_fallback(
        self,
        prompt: str,
        width: int = 1080,
        height: int = 1350,
        negative_prompt: str = "",
        model: str = "flux-dev",
        format_preset: str = "",
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: Optional[int] = None,
    ) -> ImageResult:
        """FLUX text-to-image — fallback se NB2 falhar."""
        logger.info("FLUX fallback: using text-to-image")
        if not self.configured:
            return ImageResult(success=False, error="FAL_API_KEY não configurada")

        start = time.time()
        w, h = self._get_dimensions(format_preset, width, height)
        api_w, api_h = self._get_api_dimensions(w, h)
        model_id = self.MODELS.get(model, model)

        payload = {
            "prompt": prompt,
            "image_size": {"width": api_w, "height": api_h},
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "num_images": 1,
            "enable_safety_checker": False,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed

        try:
            logger.info("FLUX generating: %s (%dx%d)", model_id, w, h)
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/{model_id}",
                    headers={
                        "Authorization": f"Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                result_data = resp.json()

            images = result_data.get("images", [])
            if not images:
                return ImageResult(success=False, error="Nenhuma imagem retornada", model_used=model)

            image_info = images[0]
            image_url = image_info.get("url", "")
            request_id = str(int(time.time() * 1000))
            image_path = await self._download(image_url, request_id, target_size=(w, h))

            cost = COST_FLUX_PRO if "pro" in model else COST_FLUX_DEV
            elapsed = time.time() - start

            if self.budget_tracker:
                try:
                    self.budget_tracker.record("nb2", cost, {"model": model})
                except Exception:
                    pass

            logger.info("FLUX gerada: %s (%.1fs, $%.4f)", image_path.name, elapsed, cost)

            return ImageResult(
                success=True,
                image_url=image_url,
                image_path=str(image_path),
                width=image_info.get("width", w),
                height=image_info.get("height", h),
                cost_usd=cost,
                elapsed_seconds=elapsed,
                request_id=request_id,
                seed=result_data.get("seed", 0),
                model_used=model,
            )

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                pass
            logger.error("FLUX HTTP error: %s — %s", e, error_body)
            return ImageResult(
                success=False,
                error=f"FLUX error {e.response.status_code}: {error_body or str(e)}",
                elapsed_seconds=time.time() - start,
                model_used=model,
            )
        except Exception as e:
            logger.error("Erro ao gerar imagem: %s", e, exc_info=True)
            return ImageResult(success=False, error=str(e), elapsed_seconds=time.time() - start, model_used=model)

    async def _download(self, url: str, request_id: str, target_size: tuple[int, int] | None = None) -> Path:
        """Baixa imagem gerada e opcionalmente redimensiona para target_size exato."""
        ext = "png"
        if ".jpg" in url or ".jpeg" in url:
            ext = "jpg"
        elif ".webp" in url:
            ext = "webp"

        filename = f"{request_id[:12]}.{ext}"
        out_path = self.output_dir / filename

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        # Ajusta para target_size SEM distorcer: crop centralizado para igualar
        # aspect ratio, depois resize proporcional. NUNCA stretch.
        if target_size:
            try:
                img = PILImage.open(out_path)
                if img.size != target_size:
                    tw, th = target_size
                    sw, sh = img.size
                    src_ratio = sw / sh
                    tgt_ratio = tw / th
                    # Crop centralizado para igualar aspect ratio
                    if abs(src_ratio - tgt_ratio) > 0.01:
                        if src_ratio > tgt_ratio:
                            # Source mais larga: cortar laterais
                            new_w = int(sh * tgt_ratio)
                            left = (sw - new_w) // 2
                            img = img.crop((left, 0, left + new_w, sh))
                        else:
                            # Source mais alta: cortar topo/rodape
                            new_h = int(sw / tgt_ratio)
                            top = (sh - new_h) // 2
                            img = img.crop((0, top, sw, top + new_h))
                        logger.info("Cropped %s: (%d,%d)→(%d,%d) para aspect %.3f", out_path.name, sw, sh, *img.size, tgt_ratio)
                    # Resize proporcional para target exato
                    if img.size != target_size:
                        logger.info("Scaling %s: %s → %s", out_path.name, img.size, target_size)
                        img = img.resize(target_size, PILImage.LANCZOS)
                    img.save(out_path, quality=95)
            except Exception as e:
                logger.warning("Resize failed (keeping original): %s", e)

        logger.info("Imagem salva: %s", out_path)
        return out_path
