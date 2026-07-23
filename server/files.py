from __future__ import annotations

from pathlib import Path


def extract_text_from_file(path: Path, file_type: str) -> str:
    file_type = (file_type or path.suffix.lstrip(".")).lower()
    if file_type == "pdf":
        return _extract_pdf(path)
    if file_type in ("doc", "docx"):
        return _extract_docx(path)
    if file_type in ("txt", "md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"不支持的文件类型：{file_type}")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf，请 pip install -r requirements.txt") from exc
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("PDF 未能提取到文本，请换可选中文本的简历文件")
    return text


def _extract_docx(path: Path) -> str:
    if path.suffix.lower() == ".doc":
        raise ValueError("暂不支持旧版 .doc，请另存为 .docx 或 PDF")
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("缺少 python-docx，请 pip install -r requirements.txt") from exc
    document = docx.Document(str(path))
    text = "\n".join(p.text for p in document.paragraphs if p.text.strip()).strip()
    if not text:
        raise ValueError("Word 未能提取到文本")
    return text
