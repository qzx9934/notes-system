# -*- coding: utf-8 -*-
"""把常见办公文档抽取为纯文本，供大模型整理成笔记。

支持：
  .txt / .md / .csv / .json   —— 直接读取
  .docx                       —— 纯标准库解析（OOXML，无需第三方库）
  .pptx                       —— 纯标准库解析（按幻灯片顺序）
  .pdf                        —— 自动尝试 pdftotext / pypdf / pymupdf（任一可用即可）

用法：
    python extract_text.py <文件1> [文件2 ...]
    python extract_text.py 资料.pdf > 资料.txt

设计原则：docx/pptx 用 zip+xml 解析，零依赖、离线可用；pdf 因格式复杂依赖外部工具，
缺失时给出清晰的安装提示而不是静默失败。
"""
import os
import re
import sys
import zipfile
import shutil
import subprocess
import xml.etree.ElementTree as ET

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def _read_plain(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def _extract_docx(path):
    """从 .docx 抽取段落文本（标准库 zip + xml）。"""
    out = []
    with zipfile.ZipFile(path) as z:
        with z.open('word/document.xml') as fp:
            tree = ET.parse(fp)
    for para in tree.iter(W_NS + 'p'):
        texts = [node.text for node in para.iter(W_NS + 't') if node.text]
        line = ''.join(texts).strip()
        if line:
            out.append(line)
    return '\n'.join(out)


def _extract_pptx(path):
    """从 .pptx 按幻灯片顺序抽取文本（标准库）。"""
    out = []
    with zipfile.ZipFile(path) as z:
        slides = sorted(
            (n for n in z.namelist()
             if re.match(r'ppt/slides/slide\d+\.xml$', n)),
            key=lambda n: int(re.search(r'(\d+)', n).group(1))
        )
        for i, name in enumerate(slides, 1):
            with z.open(name) as fp:
                tree = ET.parse(fp)
            texts = [node.text for node in tree.iter(A_NS + 't') if node.text]
            body = '\n'.join(t.strip() for t in texts if t.strip())
            if body:
                out.append('# 幻灯片 %d\n%s' % (i, body))
    return '\n\n'.join(out)


def _extract_pdf(path):
    """依次尝试 pdftotext / pypdf / pymupdf，全部缺失则报错并给安装提示。"""
    # 1) poppler 的 pdftotext 命令（质量最好）
    if shutil.which('pdftotext'):
        r = subprocess.run(['pdftotext', '-layout', path, '-'],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    # 2) pypdf
    try:
        from pypdf import PdfReader
        return '\n'.join((pg.extract_text() or '') for pg in PdfReader(path).pages)
    except Exception:
        pass
    # 3) pymupdf (fitz)
    try:
        import fitz
        doc = fitz.open(path)
        return '\n'.join(page.get_text() for page in doc)
    except Exception:
        pass
    raise RuntimeError(
        'PDF 抽取需要以下任一工具，请安装其一后重试：\n'
        '  - poppler 的 pdftotext（推荐）：apt install poppler-utils / brew install poppler\n'
        '  - pip install pypdf\n'
        '  - pip install pymupdf\n'
        '（提示：在 Claude Code 中也可直接用 Read 工具读取 PDF，无需本脚本。）'
    )


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.txt', '.md', '.markdown', '.csv', '.json', '.log'):
        return _read_plain(path)
    if ext == '.docx':
        return _extract_docx(path)
    if ext == '.pptx':
        return _extract_pptx(path)
    if ext == '.pdf':
        return _extract_pdf(path)
    if ext in ('.doc', '.ppt'):
        raise RuntimeError('旧版二进制 %s 不支持，请先另存为 %sx 格式。' % (ext, ext))
    # 兜底：当作纯文本读
    return _read_plain(path)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    chunks = []
    for path in argv:
        if not os.path.isfile(path):
            sys.stderr.write('跳过（文件不存在）：%s\n' % path)
            continue
        try:
            text = extract(path).strip()
        except Exception as e:
            sys.stderr.write('抽取失败 %s：%s\n' % (path, e))
            continue
        if len(argv) > 1:
            chunks.append('===== 文件：%s =====\n%s' % (os.path.basename(path), text))
        else:
            chunks.append(text)
    sys.stdout.write('\n\n'.join(chunks) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
