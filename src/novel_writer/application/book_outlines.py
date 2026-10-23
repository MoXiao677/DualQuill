"""全书大纲管理；当前由作者手动编辑。"""

from novel_writer.application.fields import check_fields, update_text, structured_list, text_list
from novel_writer.application.versions import record
from novel_writer.domain.models import BookOutline, VolumePlan

MODULE = {"id": "book_outlines", "name": "全书大纲管理", "status": "ready", "description": "手动编辑主题、故事起点、主线与结局。"}


def save(document, values):
    names = ("theme", "premise", "main_plot", "ending")
    check_fields(values, {*names, 'key_events', 'volumes'})
    if document.book_outline is None:
        document.book_outline = BookOutline(project_id=document.project.id)
    update_text(document.book_outline, values, names)
    if 'key_events' in values:
        document.book_outline.key_events = text_list(values['key_events'], '关键事件')
    if 'volumes' in values:
        document.book_outline.volumes = structured_list(values['volumes'],VolumePlan,'分卷')
    record(document, "book_outline", document.book_outline, "手动保存全书大纲")
