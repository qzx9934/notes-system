#!/usr/bin/env python3
"""
编号规范化工具：将原文档章节编号转换为笔记内独立编号。

适用场景：从规程/制度等正式文档中提取的笔记，编号带有原文档章节前缀。
例如原文档第17章的内容 "17.1 xxx / 17.2 xxx" 在笔记中应改为 "1 xxx / 2 xxx"。

规则：
  "17.1" → "1", "17.2" → "2", "17.3" → "3"   (两段式，去掉原文档章节前缀)
  "21.3.1" → "3.1", "8.1.1" → "1.1"           (三段式，去掉首段保留子层级)
  "3 防止锅炉四管泄漏" → "防止锅炉四管泄漏"      (纯数字小标题，去数字)
排除：参数值如 "0.25MPa"/"0.6kPa" 不会被改动（X=0 时跳过）。

用法：
  from normalize_numbers import normalize_numbers, normalize_notes_file
  # 处理单条内容
  new = normalize_numbers(content)
  # 批量处理 JSON 文件
  normalize_notes_file('input.json', 'output.json')
"""
import json
import re


def normalize_numbers(content: str) -> str:
    """
    对笔记内容中的编号做规范化处理（单次正则 pass，避免顺序处理的二次匹配）。
    """
    # Step 1: 纯数字标题行 "X 标题" → "标题" (X>=1)
    content = re.sub(
        r'(^|\n)(\s*)(\d+)\s+([\u4e00-\u9fff][^\n]*)',
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(4)}"
                  if int(m.group(3)) >= 1 else m.group(0),
        content,
        flags=re.MULTILINE,
    )

    # Step 2: X.Y(.Z)? → Y(.Z)? (X>=1)
    def _replace(m):
        prefix = m.group(1)
        x = int(m.group(2))
        y = m.group(3)
        z = m.group(4)  # None for two-level

        if x == 0:               # 参数值如 0.25MPa
            return m.group(0)
        if z is not None:        # 三段式 X.Y.Z → Y.Z
            return f"{prefix}{y}.{z}"
        return f"{prefix}{y}"    # 两段式 X.Y → Y

    content = re.sub(
        r'((?:^|\n)\s*|[。；，]\s*)'   # 前置：行首 / 中文标点后
        r'(\d+)\.(\d+)'                 # X.Y
        r'(?:\.(\d+))?'                 # .Z 可选
        r'(?=[\s\.\、\u4e00-\u9fff])',  # 后跟分隔符 / 中文
        _replace,
        content,
        flags=re.MULTILINE,
    )

    return content


def normalize_notes_file(input_path: str, output_path: str) -> list[dict]:
    """
    读取笔记 JSON 文件，对所有笔记的 content 字段做编号规范化，
    返回被修改的笔记列表，同时写入 output_path。
    输入格式：[{id, section, title, content, ...}, ...]
    """
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        notes = json.load(f)

    changed = 0
    for note in notes:
        old = note['content']
        new = normalize_numbers(old)
        if old != new:
            note['content'] = new
            changed += 1

    # 输出全部笔记（含未修改的）
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

    print(f"共 {len(notes)} 条 → 修改 {changed} 条 → {output_path}")
    return notes


# --------------- 命令行 ---------------
if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        normalize_notes_file(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2:
        # 直接输出规范化后的文本（适合管道）
        text = sys.stdin.read() if sys.argv[1] == '-' else open(sys.argv[1], encoding='utf-8').read()
        print(normalize_numbers(text))
    else:
        print("用法: python normalize_numbers.py <输入.json> <输出.json>")
        print("      python normalize_numbers.py -  (从stdin读取文本)")
