"""S2-B运行用全字段虚构数据，时间置于过去，保持S2-A冻结样本不变。"""
from datetime import datetime
from s2_a_samples import build_dataset


def build_runtime_dataset():
    dataset = build_dataset()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('created_at','updated_at','saved_at','imported_at') and isinstance(item,str):
                    value[key] = datetime.fromisoformat(item).replace(year=2020).isoformat()
                else:
                    visit(item)
        elif isinstance(value,list):
            for item in value:
                visit(item)
    visit(dataset)
    return dataset
