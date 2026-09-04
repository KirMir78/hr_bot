import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from skills import schedule_db

PDF_DIR = "/var/www/hr-agent-frontend/files"
PDF_BASE_URL = "https://hragent.sbs/files"

_FONT = None

def _register_fonts():
    """Регистрируем шрифт с поддержкой кириллицы (один раз)"""
    global _FONT
    if _FONT:
        return _FONT
    reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not os.path.exists(reg):
        reg = "/usr/share/fonts/TTF/DejaVuSans.ttf"
        bold = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
    if os.path.exists(reg):
        pdfmetrics.registerFont(TTFont("DejaVu", reg))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold if os.path.exists(bold) else reg))
        _FONT = "DejaVu"
    else:
        _FONT = "Helvetica"
    return _FONT

def generate_schedule_pdf(plan_id):
    """Генерирует красивый PDF графика и возвращает ссылку"""
    data = schedule_db.get_plan(plan_id)
    if not data:
        return None

    plan = data['plan']
    shifts = data['shifts']

    os.makedirs(PDF_DIR, exist_ok=True)
    filename = f"schedule_{plan_id}.pdf"
    path = os.path.join(PDF_DIR, filename)

    font = _register_fonts()
    bold = font + "-Bold" if font == "DejaVu" else "Helvetica-Bold"

    title_style = ParagraphStyle('Title', fontName=bold, fontSize=16, leading=20,
                                 textColor=colors.HexColor('#1F4E79'))
    sub_style = ParagraphStyle('Sub', fontName=font, fontSize=10, leading=14,
                               textColor=colors.HexColor('#555555'))
    small_style = ParagraphStyle('Small', fontName=font, fontSize=8, leading=10,
                                 textColor=colors.HexColor('#999999'))

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm,
                            title=f"График {plan['store_code']}")

    elements = []
    elements.append(Paragraph("График работы персонала", title_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(f"Торговая точка: <b>{plan['store_code']}</b> &nbsp;·&nbsp; Период: {plan['period_start']} — {plan['period_end']}", sub_style))
    strategy_name = "A — штат приоритет" if plan['strategy'] == 'A' else "B — равномерная нагрузка"
    status_name = "опубликован" if plan['status'] == 'published' else "черновик"
    elements.append(Paragraph(f"Стратегия: {strategy_name} &nbsp;·&nbsp; Статус: {status_name}", sub_style))
    elements.append(Spacer(1, 6*mm))

    table_data = [["Дата", "Сотрудник", "Роль", "Время", "Часы"]]
    for s in shifts:
        table_data.append([
            s['date'],
            f"{s['last_name']} {s['first_name']}",
            s['role_name'] or "",
            f"{s['start_time']}–{s['end_time']}",
            str(s['hours'])
        ])

    t = Table(table_data, hAlign='LEFT', colWidths=[28*mm, 55*mm, 45*mm, 30*mm, 18*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), bold),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('FONTNAME', (0, 1), (-1, -1), font),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F6FC')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 6*mm))
    elements.append(Paragraph(
        f"Сформировано HR-агентом {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        small_style))

    doc.build(elements)
    return {"path": path, "url": f"{PDF_BASE_URL}/{filename}"}
