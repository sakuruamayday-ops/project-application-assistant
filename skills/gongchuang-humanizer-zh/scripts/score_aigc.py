#!/usr/bin/env python3
"""Run the optional Chinese AIGC detector locally."""

import argparse
import json
import sys
from pathlib import Path


DEFAULT_MODEL = "yuchuantian/AIGC_detector_zhv3short"


def main() -> int:
    parser = argparse.ArgumentParser(description="本地运行中文 AIGC 检测器")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text")
    group.add_argument("--file")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    try:
        text = args.text if args.text is not None else Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    if not text.strip():
        print(json.dumps({"ok": False, "error": "文本为空"}, ensure_ascii=False))
        return 2

    try:
        import torch
        from transformers import BertForSequenceClassification, BertTokenizer

        local_only = not args.allow_download
        tokenizer = BertTokenizer.from_pretrained(args.model, local_files_only=local_only)
        model = BertForSequenceClassification.from_pretrained(
            args.model,
            local_files_only=local_only,
            use_safetensors=False,
        )
        model.eval()
        inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
        with torch.no_grad():
            scores = model(**inputs).logits[0].softmax(0)
    except Exception as exc:
        hint = "；如尚未缓存权重，请在获准后增加 --allow-download" if local_only else ""
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}{hint}"}, ensure_ascii=False))
        return 1

    human = float(scores[0].item())
    ai = float(scores[1].item())
    result = {
        "ok": True,
        "model": args.model,
        "label": "人类" if human >= ai else "AI",
        "human_probability": round(human, 6),
        "ai_probability": round(ai, 6),
        "tokens": int(inputs["input_ids"].shape[1]),
        "notice": "该结果仅为特定模型分类信号，不能证明作者身份、抄袭、事实真伪或文本质量。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
