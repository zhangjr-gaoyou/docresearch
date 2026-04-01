#!/usr/bin/env python3
"""
Compare knowledge retrieval (知识提取页「执行知识检索」管线) vs vector search (文档集「向量查询」)
on demo queries for the 招投标法 collection.

Metric (retrieval-level): for each query, success if ANY expected keyword/phrase appears in the
concatenated text of top-K retrieved units (citations vs vector chunks).

Run from repo root:
  cd backend && .venv/bin/python scripts/eval_ztb_retrieval_comparison.py

Requires:
  - knowledge_retrieval_index.json（对该文档集执行过「知识提取」）
  - FAISS 索引（文档已上传并向量化）
  - .env 中配置嵌入与 DashScope rerank（与线上一致）；否则会看到向量路错误或回退为纯向量距离序。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# project root: backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env_file(BACKEND_ROOT / ".env")

from app.services.knowledge_retrieval_service import retrieve_and_answer  # noqa: E402
from app.services.retrieval import search_and_rerank  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402

# 「招投标法」文档集（中华人民共和国招标投标法 2017 修正 PDF）
COLLECTION_ID = "a1a493e1-f521-49b0-8e96-4408855832fe"
TOP_K = 5

# (label, query, expected substrings — hit if any matches in retrieved blob)
CASES: list[tuple[str, str, list[str], str]] = [
    # common
    ("C1", "必须进行招标的工程建设项目范围包括哪些？", ["大型基础设施", "国有资金", "国际组织"], "common"),
    ("C2", "招标投标活动的基本原则是什么？", ["公开", "公平", "公正", "诚实信用"], "common"),
    ("C3", "法律如何禁止规避招标？", ["化整为零", "规避招标"], "common"),
    ("C4", "联合体投标的民事责任如何承担？", ["连带"], "common"),
    ("C5", "开标活动的基本要求是什么？", ["公开"], "common"),
    ("C6", "中标人确定后招标人需要发出什么文件？", ["中标通知书", "中标通知"], "common"),
    ("C7", "哪些情形下可以依照法律规定不进行招标？", ["抢险", "扶贫", "国家安全", "不可抗力", "可以不进行招标"], "common"),
    ("C8", "串通投标可能承担什么法律后果？", ["串通投标", "中标无效", "罚款"], "common"),
    # less common / need precise recall
    ("U1", "资格审查有哪几种方式？", ["资格预审", "资格后审", "预审", "后审"], "uncommon"),
    ("U2", "评标委员会成员人数应当符合什么要求？", ["五人", "五人以上单数", "三分之二"], "uncommon"),
    ("U3", "招标代理机构与行政机关之间能否存在隶属关系？", ["不得", "隶属"], "uncommon"),
    ("U4", "履约保证金一般不超过合同金额的多少？", ["百分之十", "10%"], "uncommon"),
    (
        "U5",
        "潜在投标人或其他利害关系人对资格预审文件或招标文件有异议的，应当在几日内提出？",
        ["十日", "10日"],
        "uncommon",
    ),
    ("U6", "强制招标的具体范围和规模标准由谁制定？", ["国务院", "发展计划部门", "标准"], "uncommon"),
]


def _blob_citations(citations: list[dict]) -> str:
    parts = []
    for c in citations:
        parts.append(str(c.get("content", "")))
        parts.append(str(c.get("section_path", "")))
    return "\n".join(parts)


def _blob_vector(results: list[dict]) -> str:
    return "\n".join(str(r.get("content", "")) for r in results)


def _blob_fusion(chunks: list[dict]) -> str:
    return "\n".join(str(x.get("content", "")) for x in chunks)


def vector_search_with_fallback(collection_id: str, query: str, top_k: int) -> tuple[list[dict], str]:
    """Returns (results like search_and_rerank, mode_label). mode_label: rerank | faiss_only | empty."""
    try:
        r = search_and_rerank(collection_id, query, top_k=top_k)
        return r, "rerank"
    except Exception:
        try:
            store = VectorStore(collection_id)
            raw = store.search(query, top_k=top_k)
            norm = [
                {"content": m.get("content", ""), "score": m.get("score", 0.0), "document_id": m.get("document_id", "")}
                for m in raw
            ]
            return norm, "faiss_only"
        except Exception:
            return [], "empty"


def hit(blob: str, keywords: list[str]) -> bool:
    b = blob or ""
    return any(kw in b for kw in keywords)


def main() -> None:
    print(f"Collection: {COLLECTION_ID} (招投标法)")
    print(f"Top-K: {TOP_K}")
    print()

    rows_k: list[bool] = []
    rows_f: list[bool] = []
    rows_v: list[bool] = []
    vec_modes: list[str] = []
    by_cat: dict[str, tuple[int, int, int, int]] = {}  # kg_hits, kg_tot, vec_hits, vec_tot

    for lid, query, kws, cat in CASES:
        # 知识检索：skip_llm=True 仅评测 citations（与线上一致的检索+段落定位+rerank，但不生成回答）
        try:
            kg = retrieve_and_answer(COLLECTION_ID, query, top_k=TOP_K, skip_llm=True)
            kg_blob = _blob_citations(kg.get("citations") or [])
            fusion_blob = _blob_fusion(kg.get("retrieved_chunks") or [])
        except Exception as e:
            kg_blob = ""
            fusion_blob = ""
            print(f"  [{lid}] knowledge retrieve error: {e}")

        vec, vec_mode = vector_search_with_fallback(COLLECTION_ID, query, TOP_K)
        vec_modes.append(vec_mode)
        vec_blob = _blob_vector(vec)
        if vec_mode == "empty":
            print(f"  [{lid}] vector search empty (check API key + index)")

        h_k = hit(kg_blob, kws)
        h_f = hit(fusion_blob, kws)
        h_v = hit(vec_blob, kws)
        rows_k.append(h_k)
        rows_f.append(h_f)
        rows_v.append(h_v)

        a, b, c, d = by_cat.get(cat, (0, 0, 0, 0))
        by_cat[cat] = (a + int(h_k), b + 1, c + int(h_v), d + 1)

        print(f"{lid} [{cat:8}] K={h_k} V={h_v}  Q={query[:40]}…")

    n = len(CASES)
    acc_k = sum(rows_k) / n if n else 0.0
    acc_f = sum(rows_f) / n if n else 0.0
    acc_v = sum(rows_v) / n if n else 0.0
    print()
    print("—" * 60)
    print(f"Overall  知识检索·最终段落/片段 citations: {sum(rows_k)}/{n} = {acc_k:.1%}")
    print(f"Overall  知识检索·RRF 融合条 retrieved_chunks: {sum(rows_f)}/{n} = {acc_f:.1%}")
    print(f"Overall  向量查询 rerank 块:                  {sum(rows_v)}/{n} = {acc_v:.1%}")
    print(f"Δ (知识检索citations − 向量): {(acc_k - acc_v) * 100:+.1f} 个百分点")
    mode_counts: dict[str, int] = {}
    for m in vec_modes:
        mode_counts[m] = mode_counts.get(m, 0) + 1
    print(f"向量侧模式统计（各 1 次/题）: {mode_counts}")
    for cat in sorted(by_cat.keys()):
        hk, tk, hv, tv = by_cat[cat]
        print(
            f"  [{cat}] 知识检索 {hk}/{tk}={hk/tk:.1%}  |  向量 {hv}/{tv}={hv/tv:.1%}"
        )
    print()
    print("说明：命中定义为「任一期望关键词出现在 Top-K 拼接文本中」；")
    print("      知识检索 citations 为段落收敛后的证据，向量块通常更大、更易覆盖短关键词。")
    print("      若 RRF 命中率明显高于 citations，说明段落定位丢掉了部分信号。")
    print("      未评测 LLM 最终回答正确性。")


if __name__ == "__main__":
    main()
