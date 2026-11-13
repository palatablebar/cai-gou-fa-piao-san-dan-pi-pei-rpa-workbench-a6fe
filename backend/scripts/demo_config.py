"""演示数据定义：46 供应商 / 180 PO / 210 GRN / 190 有效发票 + 5 条归一失败样本。

全部由固定种子确定性生成（random.Random(20261113)），并且**按测试目标反推分布**：
  - 15 张量差：对应 PO 收货量低于订单量 8%（超过 ±1% 容差）
  - 9 张价差：发票金额高出应付约 4%（超过 0.02 元容差）
  - 8 张税差：发票税率与订单税率不同
  - 6 张缺单：PO 号不在订单表内
  - 12 张重复：发票号被「发票平台」批次二次导入（自然键 = 发票号 + 采集批次）
  其余 140 张与三单完全一致 → 1 次运行产出 50 条差异。
发票号从 INV-2026-0311 起连续分配，INV-2026-0417 落在「三单一致」组，随后被重复导入，
用于验收剧本「打开 INV-2026-0417 提示重复发票」。
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from src.services.normalization_service import (
    basic_name,
    gross_from_net_cents,
    net_from_gross_cents,
    strip_supplier_suffix,
)

DEMO_PASSWORD = "Demo@2026"

DEMO_USERS = [
    ("admin@invoice3way.io", "沈砚 · 财务主管", "admin"),
    ("analyst@invoice3way.io", "何蔓 · 应付会计", "analyst"),
    ("viewer@invoice3way.io", "窦一鸣 · 供应商协同", "viewer"),
]

ORG = "联纬汽车零部件 · 财务共享中心"

PERIOD = "2026-10"
PERIOD_START = date(2026, 10, 1)

# ---------------- 供应商 ----------------

SUPPLIER_NAMES: list[str] = [
    "宁波华翔汽车部件有限公司",
    "苏州汇川精密制造有限公司",
    "上海嘉瑞紧固件股份有限公司",
    "常州德昌金属制品有限公司",
    "无锡佳通橡塑有限公司",
    "杭州富阳冲压件厂",
    "台州信达模具科技有限公司",
    "温州瑞立汽配有限公司",
    "合肥江淮底盘件有限公司",
    "芜湖伯特利制动系统有限公司",
    "南京协众汽车空调有限公司",
    "扬州亚普汽车部件股份有限公司",
    "镇江华东灯具厂",
    "盐城华源内饰件有限公司",
    "南通通达电子科技有限公司",
    "徐州金彭车架有限公司",
    "青岛海通车桥有限公司",
    "烟台胜地汽车零部件有限公司",
    "潍坊盛瑞传动股份有限公司",
    "济南中航联轴器有限公司",
    "天津博世汽车部件有限公司",
    "北京海纳川底盘有限公司",
    "保定立中车轮制造有限公司",
    "石家庄冀东紧固件有限公司",
    "郑州宇通线束有限公司",
    "武汉神龙座椅有限公司",
    "襄阳东昇机械有限公司",
    "长沙博云制动材料有限公司",
    "南昌江铃线束系统有限公司",
    "福州闽兴橡塑有限公司",
    "厦门金龙外饰件有限公司",
    "广州华德弹簧有限公司",
    "佛山南海压铸有限公司",
    "东莞鸿图精密压铸有限公司",
    "深圳市长盈精密金属有限公司",
    "惠州亿纬锂能部件有限公司",
    "柳州五菱车架厂",
    "重庆德钢汽车零部件有限公司",
    "成都航天模塑股份有限公司",
    "西安法士特传动件有限公司",
    "太原钢铁精密冲压有限公司",
    "沈阳北方弹簧制造有限公司",
    "长春一汽富维内饰有限公司",
    "哈尔滨华通焊接件有限公司",
    "大连冰山空调部件有限公司",
    "昆山正新密封件有限公司",
]

SUPPLIER_ALIASES: dict[str, str] = {
    "宁波华翔汽车部件有限公司": "华翔,宁波华翔",
    "苏州汇川精密制造有限公司": "汇川,汇川精密",
    "上海嘉瑞紧固件股份有限公司": "嘉瑞",
    "温州瑞立汽配有限公司": "瑞立",
    "天津博世汽车部件有限公司": "博世,天津博世",
    "惠州亿纬锂能部件有限公司": "亿纬",
    "柳州五菱车架厂": "五菱车架,柳州五菱",
    "长春一汽富维内饰有限公司": "富维,一汽富维",
}

MATERIALS = [
    ("MAT-1001", "前副车架总成"),
    ("MAT-1002", "制动卡钳支架"),
    ("MAT-1003", "仪表台骨架"),
    ("MAT-1004", "座椅滑轨组件"),
    ("MAT-1005", "车门铰链"),
    ("MAT-1006", "线束护套"),
    ("MAT-1007", "轮毂轴承单元"),
    ("MAT-1008", "密封条 TPE 料"),
    ("MAT-1009", "空调冷凝器芯体"),
    ("MAT-1010", "减震器顶胶"),
    ("MAT-1011", "变速箱悬置"),
    ("MAT-1012", "行李箱锁扣"),
]

TAX_CYCLE = [1300, 1300, 900, 600, 300, 100]

# ---------------- 分布常量 ----------------
ORDER_COUNT = 180
QTY_DIFF_SLOTS = range(0, 15)  # 15 张量差
PRICE_DIFF_SLOTS = range(15, 24)  # 9 张价差
MATCHED_SLOTS = range(24, 164)  # 140 张三单一致
TAX_DIFF_SLOTS = range(164, 172)  # 8 张税差
SILENT_SLOTS = range(172, 180)  # 8 张订单本期未开票
SPLIT_SLOTS = range(24, 54)  # 30 张订单分两批收货
DUPLICATE_SLOTS = [106, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]  # 12 张重复导入
MISSING_SLOTS = range(172, 178)  # 6 张缺单

INVOICE_START_SEQ = 311
SRM_BATCH = "SRM-2026-10"
PLATFORM_BATCH = "INV-PLATFORM-2026-10"


def invoice_no(seq: int) -> str:
    return f"INV-2026-{seq:04d}"


def build_suppliers() -> list[dict]:
    rng = random.Random(20261113)
    items: list[dict] = []
    for index, name in enumerate(SUPPLIER_NAMES):
        tolerance_amount = 2 if index % 3 else 5  # 大多 0.02 元，少数 0.05 元
        tolerance_qty = 1.0 if index % 5 else 2.0
        items.append(
            {
                "code": f"SUP-{index + 1:04d}",
                "name": name,
                "alias": SUPPLIER_ALIASES.get(name),
                "contact": f"采购对接 {rng.randint(10, 99)}",
                "tolerance_amount_cents": tolerance_amount,
                "tolerance_qty_pct": tolerance_qty,
                "note": "月结 60 天" if index % 2 else "月结 30 天",
            }
        )
    return items


def build_orders(suppliers: list[dict]) -> list[dict]:
    items: list[dict] = []
    for index in range(ORDER_COUNT):
        supplier = suppliers[(index * 7) % len(suppliers)]
        material_code, material_name = MATERIALS[index % len(MATERIALS)]
        qty = 120 + (index * 7) % 380
        unit_price = 900 + (index * 37) % 35000
        items.append(
            {
                "po_no": f"PO-2026-{index + 1:04d}",
                "supplier_code": supplier["code"],
                "material_code": material_code,
                "material_name": material_name,
                "qty": qty,
                "unit_price_cents": unit_price,
                "tax_rate_bp": TAX_CYCLE[index % len(TAX_CYCLE)],
                "ordered_on": date(2026, 9, 1) + timedelta(days=index % 28),
                "slot": index,
            }
        )
    return items


def build_receipts(orders: list[dict]) -> list[dict]:
    """210 张收货单：180 张基础 + 30 张分批第二张；量差订单少收 8%。"""
    items: list[dict] = []
    grn_seq = 0
    for order in orders:
        slot = order["slot"]
        qty = order["qty"]
        if slot in QTY_DIFF_SLOTS:
            shortfall = max(3, round(qty * 0.08))
            first_qty = qty - shortfall
            grn_seq += 1
            items.append(
                {
                    "grn_no": f"GRN-2026-{grn_seq:04d}",
                    "po_no": order["po_no"],
                    "qty": first_qty,
                    "received_on": date(2026, 10, 3) + timedelta(days=slot % 20),
                    "batch": f"B{1 + slot % 9:02d}",
                }
            )
            continue
        if slot in SPLIT_SLOTS:
            first_qty = qty // 2
            second_qty = qty - first_qty
            for part, part_qty in enumerate((first_qty, second_qty)):
                grn_seq += 1
                items.append(
                    {
                        "grn_no": f"GRN-2026-{grn_seq:04d}",
                        "po_no": order["po_no"],
                        "qty": part_qty,
                        "received_on": date(2026, 10, 5) + timedelta(days=(slot + part * 3) % 20),
                        "batch": f"B{1 + (slot + part) % 9:02d}",
                    }
                )
            continue
        grn_seq += 1
        items.append(
            {
                "grn_no": f"GRN-2026-{grn_seq:04d}",
                "po_no": order["po_no"],
                "qty": qty,
                "received_on": date(2026, 10, 4) + timedelta(days=slot % 20),
                "batch": f"B{1 + slot % 9:02d}",
            }
        )
    return items


def _supplier_variant(order_supplier_name: str, supplier_index: int, aliases: list[str]) -> str:
    """同一供应商在原始单据里的三种写法：全名 / 带空白 / 别名或简称（都要能被算法 A 归一）。"""
    variant = supplier_index % 4
    if variant == 0:
        return order_supplier_name
    if variant == 1:
        return f"  {order_supplier_name} "  # 带空白
    if variant == 2 and aliases:
        return aliases[0]
    return strip_supplier_suffix(basic_name(order_supplier_name)) or order_supplier_name


def build_invoice_rows(suppliers: list[dict], orders: list[dict], receipts: list[dict]) -> list[dict]:
    """返回 178 条唯一发票 + 12 条重复导入 + 5 条归一失败样本（共 195 行原始数据）。"""
    supplier_by_code = {supplier["code"]: supplier for supplier in suppliers}
    supplier_pos = {supplier["code"]: index for index, supplier in enumerate(suppliers)}
    received_qty: dict[str, int] = {}
    for receipt in receipts:
        received_qty[receipt["po_no"]] = received_qty.get(receipt["po_no"], 0) + receipt["qty"]

    rows: list[dict] = []
    for slot_index, order in enumerate(orders[:172]):
        seq = INVOICE_START_SEQ + slot_index
        supplier = supplier_by_code[order["supplier_code"]]
        supplier_pos_index = supplier_pos[order["supplier_code"]]
        own_aliases = [part.strip() for part in (supplier["alias"] or "").split(",") if part.strip()]
        base_name = _supplier_variant(supplier["name"], supplier_pos_index, own_aliases)
        received = received_qty.get(order["po_no"], 0)
        payable = gross_from_net_cents(received * order["unit_price_cents"], order["tax_rate_bp"])
        issue_day = PERIOD_START + timedelta(days=slot_index % 27)
        if slot_index in QTY_DIFF_SLOTS:
            amount = gross_from_net_cents(order["qty"] * order["unit_price_cents"], order["tax_rate_bp"])
        elif slot_index in PRICE_DIFF_SLOTS:
            amount = payable + max(100, payable // 25)
        elif slot_index in TAX_DIFF_SLOTS:
            other_bp = 900 if order["tax_rate_bp"] == 1300 else 1300
            amount = gross_from_net_cents(received * order["unit_price_cents"], other_bp)
        else:
            amount = payable
        tax_bp = order["tax_rate_bp"]
        if slot_index in TAX_DIFF_SLOTS:
            tax_bp = 900 if tax_bp == 1300 else 1300
        rows.append(
            {
                "invoice_no": invoice_no(seq),
                "import_batch": SRM_BATCH,
                "supplier_name": base_name,
                "po_no": order["po_no"],
                "material_code": order["material_code"],
                "amount": f"{amount / 100:.2f}",
                "tax_rate": f"{tax_bp / 100:g}%",
                "issued_on": issue_day,
                "is_red": False,
                "slot": slot_index,
            }
        )

    for offset, slot_index in enumerate(MISSING_SLOTS):
        seq = INVOICE_START_SEQ + 172 + offset
        supplier = suppliers[(slot_index * 5) % len(suppliers)]
        rows.append(
            {
                "invoice_no": invoice_no(seq),
                "import_batch": SRM_BATCH,
                "supplier_name": supplier["name"],
                "po_no": f"PO-2026-9{slot_index:03d}",
                "material_code": f"MAT-9{slot_index:03d}",
                "amount": f"{(68000 + slot_index * 137) / 100:.2f}",
                "tax_rate": "13%",
                "issued_on": PERIOD_START + timedelta(days=slot_index % 20),
                "is_red": False,
                "slot": slot_index,
            }
        )

    # 12 张重复发票：发票平台批次把同一号码又导入一次
    original_by_seq = {row["invoice_no"]: row for row in rows}
    for seq_offset in DUPLICATE_SLOTS:
        original = original_by_seq.get(invoice_no(INVOICE_START_SEQ + seq_offset))
        if original is None:
            continue
        rows.append(
            {
                **original,
                "import_batch": PLATFORM_BATCH,
                "issued_on": original["issued_on"],
                "slot": original["slot"] + 1000,
            }
        )
    return rows


def build_rejected_rows() -> list[dict]:
    """5 行归一失败样本：金额非数字 / 非标准税率 / 供应商为空 / 日期非法 / 金额为 0。"""
    return [
        {
            "invoice_no": "INV-2026-9001",
            "import_batch": SRM_BATCH,
            "supplier_name": "宁波华翔汽车部件有限公司",
            "po_no": "PO-2026-0181",
            "amount": "N/A",
            "tax_rate": "13%",
            "issued_on": date(2026, 10, 9),
        },
        {
            "invoice_no": "INV-2026-9002",
            "import_batch": SRM_BATCH,
            "supplier_name": "苏州汇川精密制造有限公司",
            "po_no": "PO-2026-0182",
            "amount": "18,600.00",
            "tax_rate": "7%",
            "issued_on": date(2026, 10, 10),
        },
        {
            "invoice_no": "INV-2026-9003",
            "import_batch": SRM_BATCH,
            "supplier_name": "",
            "po_no": "PO-2026-0183",
            "amount": "9200.00",
            "tax_rate": "13%",
            "issued_on": date(2026, 10, 11),
        },
        {
            "invoice_no": "INV-2026-9004",
            "import_batch": SRM_BATCH,
            "supplier_name": "上海嘉瑞紧固件股份有限公司",
            "po_no": "PO-2026-0184",
            "amount": "7400.00",
            "tax_rate": "13%",
            "issued_on": "2026-13-40",
        },
        {
            "invoice_no": "INV-2026-9005",
            "import_batch": SRM_BATCH,
            "supplier_name": "温州瑞立汽配有限公司",
            "po_no": "PO-2026-0185",
            "amount": "0",
            "tax_rate": "13%",
            "issued_on": date(2026, 10, 12),
        },
    ]


def tax_breakdown(amount_cents: int, tax_rate_bp: int) -> int:
    return amount_cents - net_from_gross_cents(amount_cents, tax_rate_bp)


SEED_RUN = {
    "seed_key": "seed-run-2026-10",
    "period": PERIOD,
    "trigger": "seed",
    "operator": "admin@invoice3way.io",
}
