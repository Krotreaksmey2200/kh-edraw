from __future__ import annotations
# Source Generated with Decompyle++
# File: custom_curve_tool.pyc (Python 3.12)

__doc__ = '\ncore/custom_curve_tool.py\nSinh & nạp công cụ vẽ đường cong mới do người dùng mô tả → Gemini sinh mã Python.\n\nPipeline:\n  1. Người dùng nhập prompt mô tả công cụ vẽ.\n  2. Ghép prompt với hệ chỉ dẫn (PROMPT_HEADER) → gửi Gemini.\n  3. Gemini trả về một code fence ```python``` chứa hàm:\n        def build_path(p0, p3) -> QPainterPath\n  4. compile_curve_tool() làm sạch / lọc bảo mật / exec trong sandbox /\n     test thử bằng 2 điểm dummy → trả về dict tool đã sẵn dùng.\n  5. Caller (main_window) nạp tool vào DrawingEngine.custom_tools và thêm\n     mục mới vào menu nhóm Đường cong.\n\nSandbox không phải là sandbox bảo mật tuyệt đối — chỉ chặn các từ khoá nguy\nhiểm phổ biến và giới hạn __builtins__. Người dùng được cảnh báo trong UI.\n'
import math
import re
import traceback
from typing import Callable
from PyQt6.QtCore import QObject, QPointF, QRectF, QThread, pyqtSignal
from PyQt6.QtGui import QPainterPath, QPolygonF, QTransform
from core.i18n import t
PROMPT_HEADER = '\nBạn là chuyên gia Python/PyQt6, hỗ trợ ứng dụng vẽ eDraw thêm CÔNG CỤ VẼ\nĐƯỜNG CONG mới do người dùng mô tả.\n\nNHIỆM VỤ\n========\nSinh ra MỘT (và chỉ một) hàm Python tên `build_path(points)` trả về một\nQPainterPath thể hiện đường cong THOẢ ĐIỀU KIỆN ĐI/QUA / phụ thuộc các\nđiểm trong `points` đúng theo mô tả của người dùng.\n\nINPUT\n=====\n- `points` là `list[QPointF]` — các điểm người dùng đã nhấp trên bảng,\n  theo đúng thứ tự nhấp (`points[i].x()`, `points[i].y()` là toạ độ).\n- Số điểm cần nhấp được khai báo qua metadata `# N_POINTS: K`\n  (số nguyên 2 ≤ K ≤ 10). Ứng dụng chỉ commit khi đủ K điểm.\n- Trong giai đoạn preview (đã nhấp k < K điểm), ứng dụng vẫn gọi\n  `build_path(points)` với danh sách độ dài k+1 (k điểm đã nhấp + 1 điểm\n  theo con trỏ chuột). Hàm phải tự xử lý:\n    • Khi `len(points) < N_POINTS`: trả `QPainterPath()` rỗng (hoặc một\n      preview hợp lý) — TUYỆT ĐỐI KHÔNG được raise exception.\n    • Khi điểm bị suy biến (trùng nhau, thẳng hàng làm hệ vô nghiệm…):\n      trả `QPainterPath()` rỗng, không raise.\n\nOUTPUT\n======\n- Trả về `QPainterPath` thể hiện đường cong / đồ thị thoả mô tả người dùng,\n  đi qua hoặc phụ thuộc các điểm trong `points` đúng vai trò mô tả.\n- Khi không đủ điểm để dựng → `QPainterPath()` rỗng.\n\nVAI TRÒ CỦA TỪNG ĐIỂM\n=====================\nNgười dùng có thể yêu cầu các vai trò khác nhau cho từng điểm. Ví dụ:\n- "Đồ thị bậc 3 đi qua 3 điểm A, B, C"  → 3 điểm đều là điểm đường cong đi qua.\n- "Parabol đỉnh I, đi qua điểm M"        → điểm 1 = đỉnh, điểm 2 = điểm trên parabol.\n- "Đường tròn tâm O, đi qua điểm M"      → điểm 1 = tâm, điểm 2 = điểm trên đường.\nHãy ĐỌC MÔ TẢ CỦA NGƯỜI DÙNG để đặt đúng vai trò; nếu mô tả không nói rõ,\nmặc định coi tất cả điểm là điểm đường cong đi qua.\n\nĐỊNH DẠNG ĐẦU RA (BẮT BUỘC)\n===========================\n- Trả về DUY NHẤT một code fence Python:\n  ```python\n  ...\n  ```\n- BA dòng đầu của khối code BẮT BUỘC là metadata:\n    # NAME: <ten_ngan_khong_dau_cach>      (a-z/A-Z/0-9/_, bắt đầu bằng chữ, ≤ 24 ký tự)\n    # DESC: <ការពិពណ៌នាជាភាសាខ្មែរ 1 បន្ទាត់>\n    # N_POINTS: <K — số điểm cần nhấp, nguyên 2..10>\n- Sau đó là khai báo:\n    def build_path(points):\n        ...\n        return path                     # path là QPainterPath\n- KHÔNG được xuất văn bản nào ngoài code fence (không lời giải thích, không ví dụ).\n\nNAMESPACE CÓ SẴN (KHÔNG được import)\n====================================\n- math\n- QPointF, QRectF\n- QPainterPath, QPolygonF, QTransform\n\nCẤM\n===\n- import (bất kể module gì, kể cả `import math`).\n- exec / eval / compile / open / __import__ / globals / locals.\n- truy cập file, network, subprocess, os, sys, threading, ctypes…\n- vòng lặp chạy hơn 10000 lần (giữ hiệu năng realtime).\n- truy cập thuộc tính bắt đầu/kết thúc bằng `__` (dunder).\n\nCHẤT LƯỢNG ĐƯỜNG CONG\n=====================\n- Hàm phải thuần (không side effect).\n- Đường cong nên đủ mượt: dùng `quadTo` / `cubicTo` / `arcTo` khi hợp lý;\n  nếu sample bằng `lineTo` thì 100–400 đoạn là đủ.\n- Nếu hàm cần solve hệ phương trình, viết tay bằng định thức / Cramer\n  (không có numpy, scipy).\n\nVÍ DỤ MẪU\n=========\n\nVí dụ 1 — Đường xoắn ốc Archimedes (2 điểm: tâm + biên ngoài)\n```python\n# NAME: spiral\n# DESC: Đường xoắn ốc Archimedes từ điểm 1 toả ra điểm 2 (3 vòng)\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    p0, p3 = points[0], points[1]\n    dx = p3.x() - p0.x()\n    dy = p3.y() - p0.y()\n    r_max = math.hypot(dx, dy)\n    if r_max < 1.0:\n        return path\n    base_angle = math.atan2(dy, dx)\n    n = 240\n    path.moveTo(p0)\n    for i in range(1, n + 1):\n        t = i / n\n        r = r_max * t\n        a = base_angle + 6.0 * math.pi * t\n        path.lineTo(QPointF(p0.x() + r * math.cos(a),\n                            p0.y() + r * math.sin(a)))\n    return path\n```\n\nVí dụ 2 — Đồ thị hàm trùng phương ax^4 + bx^2 + cx ĐI QUA 3 điểm\n```python\n# NAME: quartic_abc_3\n# DESC: Đồ thị y = a*x^4 + b*x^2 + c*x đi qua 3 điểm người dùng nhấp\n# N_POINTS: 3\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 3:\n        return path\n    pts = [(p.x(), p.y()) for p in points[:3]]\n\n    # Hệ 3 phương trình ẩn (a, b, c): a*x_i^4 + b*x_i^2 + c*x_i = y_i\n    M = [[p[0] ** 4, p[0] ** 2, p[0]] for p in pts]\n    Y = [p[1] for p in pts]\n\n    def det3(m):\n        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])\n              - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])\n              + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))\n\n    D = det3(M)\n    if abs(D) < 1e-9:\n        return path\n    Ma = [[Y[i], M[i][1], M[i][2]] for i in range(3)]\n    Mb = [[M[i][0], Y[i], M[i][2]] for i in range(3)]\n    Mc = [[M[i][0], M[i][1], Y[i]] for i in range(3)]\n    a = det3(Ma) / D\n    b = det3(Mb) / D\n    c = det3(Mc) / D\n\n    xs = [p[0] for p in pts]\n    x_min = min(xs)\n    x_max = max(xs)\n    span = max(1.0, x_max - x_min)\n    x_lo = x_min - 0.25 * span\n    x_hi = x_max + 0.25 * span\n\n    n = 300\n    first = True\n    for i in range(n + 1):\n        t = i / n\n        x = x_lo + (x_hi - x_lo) * t\n        y = a * x ** 4 + b * x ** 2 + c * x\n        pt = QPointF(x, y)\n        if first:\n            path.moveTo(pt)\n            first = False\n        else:\n            path.lineTo(pt)\n    return path\n```\n'.strip()
PROMPT_HEADER_CURVE = PROMPT_HEADER
PROMPT_HEADER_LINE = '\nBạn là chuyên gia Python/PyQt6, hỗ trợ ứng dụng vẽ eDraw thêm CÔNG CỤ VẼ ĐOẠN NỐI\nmới do người dùng mô tả.\n\nNHIỆM VỤ\n========\nSinh ra MỘT (và chỉ một) hàm Python tên `build_path(points)` trả về QPainterPath\nlà đường/đoạn nối giữa 2 điểm đầu mút — có thể kèm trang trí (đầu mũi tên đặc biệt,\nngoặc, vạch chặn, lượn sóng, ziczac, v.v.) theo mô tả người dùng.\n\nINPUT\n=====\n- `points` có ĐÚNG 2 phần tử:\n    • points[0] — điểm bắt đầu (P_start).\n    • points[1] — điểm kết thúc (P_end).\n- Preview (len < 2): trả QPainterPath() rỗng, TUYỆT ĐỐI không raise exception.\n- Khi 2 điểm trùng nhau (khoảng cách < 1.0): trả QPainterPath() rỗng.\n\nOUTPUT\n======\n- QPainterPath đi từ points[0] đến points[1], kèm trang trí theo mô tả.\n- Không nhất thiết là đường thẳng: có thể lượn sóng, gấp khúc, v.v.\n  nhưng phải rõ ràng "nối" hai điểm đầu mút.\n\nĐỊNH DẠNG ĐẦU RA (BẮT BUỘC)\n===========================\n- Trả về DUY NHẤT một code fence Python:\n  ```python\n  ...\n  ```\n- BA dòng đầu BẮT BUỘC:\n    # NAME: <ten_ngan_khong_dau_cach>      (a-z/A-Z/0-9/_, bắt đầu bằng chữ, ≤ 24 ký tự)\n    # DESC: <ការពិពណ៌នាជាភាសាខ្មែរ 1 បន្ទាត់>\n    # N_POINTS: 2                           ← PHẢI là 2, không được thay đổi\n- Sau đó:\n    def build_path(points):\n        ...\n        return path\n- KHÔNG xuất văn bản nào ngoài code fence.\n\nNAMESPACE CÓ SẴN (KHÔNG được import)\n====================================\n- math\n- QPointF, QRectF\n- QPainterPath, QPolygonF, QTransform\n\nCẤM\n===\n- import (bất kể module gì, kể cả `import math`).\n- exec / eval / compile / open / __import__ / globals / locals.\n- Truy cập file, network, subprocess, os, sys, threading, ctypes.\n- Vòng lặp chạy hơn 10 000 lần.\n- Thuộc tính dunder (__xx__).\n\nCHẤT LƯỢNG\n==========\n- Hàm thuần (không side effect).\n- Tính vector song song/vuông góc từ 2 điểm: ux,uy = dx/L, dy/L; nx,ny = -uy, ux.\n- Nếu sample bằng lineTo: 60–200 đoạn là đủ.\n\nVÍ DỤ MẪU\n=========\n\nVí dụ 1 — Đường lượn sóng sine nối 2 điểm\n```python\n# NAME: wave_connector\n# DESC: Đường lượn sóng sine nối 2 điểm (4 chu kỳ)\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    p0, p1 = points[0], points[1]\n    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()\n    L = math.hypot(dx, dy)\n    if L < 1.0:\n        return path\n    ux, uy = dx / L, dy / L\n    nx, ny = -uy, ux\n    amp = min(L * 0.07, 9.0)\n    n = 160\n    path.moveTo(p0)\n    for i in range(1, n + 1):\n        t = i / n\n        wave = amp * math.sin(2 * math.pi * 4 * t)\n        path.lineTo(QPointF(p0.x() + t * dx + wave * nx,\n                            p0.y() + t * dy + wave * ny))\n    return path\n```\n\nVí dụ 2 — Đoạn nối gấp khúc ziczac đều\n```python\n# NAME: zigzag_connector\n# DESC: Đường gấp khúc ziczac nối 2 điểm (8 nấc)\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    p0, p1 = points[0], points[1]\n    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()\n    L = math.hypot(dx, dy)\n    if L < 1.0:\n        return path\n    ux, uy = dx / L, dy / L\n    nx, ny = -uy, ux\n    segs = 8\n    amp = min(L * 0.07, 8.0)\n    path.moveTo(p0)\n    for k in range(1, segs + 1):\n        t = k / segs\n        side = amp if k % 2 == 1 else -amp\n        path.lineTo(QPointF(p0.x() + t * dx + side * nx,\n                            p0.y() + t * dy + side * ny))\n    path.lineTo(p1)\n    return path\n```\n'.strip()
PROMPT_HEADER_GEOMETRY = '\nBạn là chuyên gia Python/PyQt6 và hình học phẳng, hỗ trợ ứng dụng vẽ eDraw thêm\nCÔNG CỤ DỰNG ĐIỂM / ĐƯỜNG ĐẶC BIỆT từ các điểm người dùng cho trước.\n\nNHIỆM VỤ\n========\nSinh ra MỘT (và chỉ một) hàm Python tên `build_path(points)` trả về QPainterPath\nbiểu diễn đối tượng hình học được dựng từ các điểm đã nhấp: điểm đặc biệt\n(trung điểm, trọng tâm, trực tâm, tâm ngoại tiếp, tâm nội tiếp...), hoặc đường\nđặc biệt (đường trung trực, đường phân giác, đường cao, trung tuyến, tiếp tuyến,\nđường Euler...) theo mô tả người dùng.\n\nINPUT\n=====\n- `points` là `list[QPointF]`, theo đúng thứ tự người dùng nhấp.\n- Số điểm cần nhấp khai báo bằng `# N_POINTS: K` (2 ≤ K ≤ 10).\n- Preview khi `len(points) < K`: trả `QPainterPath()` rỗng hoặc preview hợp lý,\n  tuyệt đối không raise exception.\n- Suy biến (điểm trùng nhau, tam giác gần thẳng hàng, góc không xác định, mẫu số\n  gần 0...): trả `QPainterPath()` rỗng, không raise.\n\nOUTPUT\n======\n- Luôn trả về QPainterPath.\n- Nếu đối tượng là ĐIỂM: vẽ marker nhỏ tại điểm dựng được, ví dụ vòng tròn bán\n  kính 4-6 px kèm dấu cộng nhỏ. Không chỉ `moveTo()` một điểm đơn lẻ vì nét sẽ\n  không nhìn thấy.\n- Nếu đối tượng là ĐƯỜNG THẲNG/TIA: vẽ đoạn đủ dài bằng `moveTo/lineTo`, thường\n  dùng `arm = 250.0` mỗi phía cho đường thẳng vô hạn.\n- Nếu đối tượng là ĐOẠN/ĐƯỜNG GẤP: vẽ đúng các đoạn cần hiển thị.\n- Không vẽ các điểm đầu vào trừ khi mô tả yêu cầu; chỉ vẽ kết quả dựng.\n\nVAI TRÒ ĐIỂM\n============\nĐọc kỹ mô tả người dùng để gán vai trò:\n- "trung điểm AB" → points[0]=A, points[1]=B.\n- "trọng tâm tam giác ABC" → points[0]=A, points[1]=B, points[2]=C.\n- "đường phân giác trong tại A của góc BAC" → points[0]=A, points[1]=B, points[2]=C.\n- "trực tâm tam giác ABC" → points[0]=A, points[1]=B, points[2]=C.\nNếu mô tả không nói rõ, mặc định các điểm được đặt tên A, B, C, D... theo thứ tự.\n\nĐỊNH DẠNG ĐẦU RA (BẮT BUỘC)\n===========================\n- Trả về DUY NHẤT một code fence Python:\n  ```python\n  ...\n  ```\n- BA dòng đầu BẮT BUỘC:\n    # NAME: <ten_ngan_khong_dau_cach>      (a-z/A-Z/0-9/_, bắt đầu bằng chữ, ≤ 24 ký tự)\n    # DESC: <ការពិពណ៌នាជាភាសាខ្មែរ 1 បន្ទាត់>\n    # N_POINTS: <K>\n- Sau đó:\n    def build_path(points):\n        ...\n        return path\n- KHÔNG xuất văn bản nào ngoài code fence.\n\nNAMESPACE CÓ SẴN (KHÔNG được import)\n====================================\n- math\n- QPointF, QRectF\n- QPainterPath, QPolygonF, QTransform\n\nCẤM\n===\n- import (bất kể module gì, kể cả `import math`).\n- exec / eval / compile / open / __import__ / globals / locals.\n- Truy cập file, network, subprocess, os, sys, threading, ctypes.\n- Vòng lặp chạy hơn 10 000 lần.\n- Thuộc tính dunder (__xx__).\n\nKỸ THUẬT HÌNH HỌC NÊN DÙNG\n==========================\n- Dùng `math.hypot(dx, dy)` để kiểm tra độ dài và chuẩn hoá vector.\n- Vector đơn vị AB: `ux, uy = dx / L, dy / L`; pháp tuyến: `nx, ny = -uy, ux`.\n- Với đường qua điểm P theo vector (ux,uy), vẽ dài: P ± arm*(ux,uy).\n- Với marker điểm, dùng `path.addEllipse(QRectF(x-r, y-r, 2*r, 2*r))` và 2 nét chéo/cộng.\n- Với giao hai đường thẳng, dùng định thức; nếu `abs(det) < 1e-9` thì trả rỗng.\n\nVÍ DỤ MẪU\n=========\n\nVí dụ 1 — Trung điểm\n```python\n# NAME: midpoint_2\n# DESC: Trung điểm\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    p0, p1 = points[0], points[1]\n    if math.hypot(p1.x() - p0.x(), p1.y() - p0.y()) < 1.0:\n        return path\n    x = (p0.x() + p1.x()) / 2.0\n    y = (p0.y() + p1.y()) / 2.0\n    r = 5.0\n    path.addEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))\n    path.moveTo(QPointF(x - 8.0, y))\n    path.lineTo(QPointF(x + 8.0, y))\n    path.moveTo(QPointF(x, y - 8.0))\n    path.lineTo(QPointF(x, y + 8.0))\n    return path\n```\n\nVí dụ 2 — Đường trung trực của đoạn AB\n```python\n# NAME: perpendicular_bisector\n# DESC: Đường trung trực\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    p0, p1 = points[0], points[1]\n    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()\n    L = math.hypot(dx, dy)\n    if L < 1.0:\n        return path\n    mid_x = (p0.x() + p1.x()) / 2.0\n    mid_y = (p0.y() + p1.y()) / 2.0\n    ux, uy = dx / L, dy / L\n    nx, ny = -uy, ux\n    arm = 250.0\n    path.moveTo(QPointF(mid_x - nx * arm, mid_y - ny * arm))\n    path.lineTo(QPointF(mid_x + nx * arm, mid_y + ny * arm))\n    return path\n```\n\nVí dụ 3 — Trọng tâm tam giác ABC\n```python\n# NAME: centroid_abc\n# DESC: Trọng tâm tam giác tạo bởi 3 điểm A, B, C\n# N_POINTS: 3\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 3:\n        return path\n    a, b, c = points[0], points[1], points[2]\n    area2 = ((b.x() - a.x()) * (c.y() - a.y())\n             - (b.y() - a.y()) * (c.x() - a.x()))\n    if abs(area2) < 1.0:\n        return path\n    x = (a.x() + b.x() + c.x()) / 3.0\n    y = (a.y() + b.y() + c.y()) / 3.0\n    r = 5.0\n    path.addEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))\n    path.moveTo(QPointF(x - 8.0, y))\n    path.lineTo(QPointF(x + 8.0, y))\n    path.moveTo(QPointF(x, y - 8.0))\n    path.lineTo(QPointF(x, y + 8.0))\n    return path\n```\n'.strip()
PROMPT_HEADER_POLYGON = '\nBạn là chuyên gia Python/PyQt6, hỗ trợ ứng dụng vẽ eDraw thêm CÔNG CỤ VẼ\nĐA GIÁC / HÌNH KHÉP KÍN mới do người dùng mô tả.\n\nNHIỆM VỤ\n========\nSinh ra MỘT (và chỉ một) hàm Python tên `build_path(points)` trả về QPainterPath\nlà hình khép kín (đa giác, hình sao, hình đặc biệt, v.v.) thoả mô tả người dùng.\n\nINPUT\n=====\n- `points` là `list[QPointF]` — các điểm người dùng nhấp theo thứ tự.\n- Số điểm cần khai báo qua `# N_POINTS: K` (2 ≤ K ≤ 10).\n- Preview (len < K): trả QPainterPath() rỗng, TUYỆT ĐỐI không raise exception.\n- Suy biến (điểm trùng nhau, quá gần): trả QPainterPath() rỗng, không raise.\n\nOUTPUT\n======\n- QPainterPath khép kín — BẮT BUỘC gọi `path.closeSubpath()` để khép hình.\n\nVAI TRÒ CỦA TỪNG ĐIỂM\n=====================\nVí dụ: "tâm + điểm biên", "3 đỉnh tam giác", "2 góc đối diện hình chữ nhật"…\nĐọc mô tả người dùng để đặt đúng vai trò; nếu không rõ, coi tất cả là đỉnh của đa giác.\n\nĐỊNH DẠNG ĐẦU RA (BẮT BUỘC)\n===========================\n- Trả về DUY NHẤT một code fence Python:\n  ```python\n  ...\n  ```\n- BA dòng đầu BẮT BUỘC:\n    # NAME: <ten_ngan_khong_dau_cach>\n    # DESC: <ការពិពណ៌នាជាភាសាខ្មែរ 1 បន្ទាត់>\n    # N_POINTS: <K>\n- KHÔNG xuất văn bản nào ngoài code fence.\n\nNAMESPACE CÓ SẴN (KHÔNG được import)\n====================================\n- math\n- QPointF, QRectF\n- QPainterPath, QPolygonF, QTransform\n\nCẤM\n===\n- import (bất kể module gì, kể cả `import math`).\n- exec / eval / compile / open / __import__ / globals / locals.\n- Truy cập file, network, subprocess, os, sys, threading, ctypes.\n- Vòng lặp chạy hơn 10 000 lần.\n- Thuộc tính dunder (__xx__).\n\nCHẤT LƯỢNG\n==========\n- Hàm thuần (không side effect).\n- Luôn gọi path.closeSubpath() để khép hình.\n- Nếu sample bằng lineTo: 100–400 đoạn là đủ.\n\nVÍ DỤ MẪU\n=========\n\nVí dụ 1 — Hình thoi: tâm + 1 đỉnh\n```python\n# NAME: rhombus\n# DESC: Hình thoi: điểm 1 = tâm, điểm 2 = một đỉnh\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    cx, cy = points[0].x(), points[0].y()\n    dx = points[1].x() - cx\n    dy = points[1].y() - cy\n    if math.hypot(dx, dy) < 1.0:\n        return path\n    path.moveTo(QPointF(cx + dx,  cy + dy))\n    path.lineTo(QPointF(cx - dy,  cy + dx))\n    path.lineTo(QPointF(cx - dx,  cy - dy))\n    path.lineTo(QPointF(cx + dy,  cy - dx))\n    path.closeSubpath()\n    return path\n```\n\nVí dụ 2 — Hình sao 5 cánh: tâm + 1 đỉnh ngoài\n```python\n# NAME: star5\n# DESC: Hình sao 5 cánh: điểm 1 = tâm, điểm 2 = đỉnh cánh ngoài\n# N_POINTS: 2\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    cx, cy = points[0].x(), points[0].y()\n    r_out = math.hypot(points[1].x() - cx, points[1].y() - cy)\n    if r_out < 1.0:\n        return path\n    r_in = r_out * 0.382\n    base = math.atan2(points[1].y() - cy, points[1].x() - cx)\n    n = 5\n    verts = []\n    for i in range(n):\n        a_out = base + 2 * math.pi * i / n\n        a_in  = a_out + math.pi / n\n        verts.append(QPointF(cx + r_out * math.cos(a_out), cy + r_out * math.sin(a_out)))\n        verts.append(QPointF(cx + r_in  * math.cos(a_in),  cy + r_in  * math.sin(a_in)))\n    path.moveTo(verts[0])\n    for v in verts[1:]:\n        path.lineTo(v)\n    path.closeSubpath()\n    return path\n```\n'.strip()
PROMPT_HEADER_FREE = '\nBạn là chuyên gia Python/PyQt6, hỗ trợ ứng dụng vẽ eDraw thêm CÔNG CỤ VẼ TỰ DO.\n\nNHIỆM VỤ\n========\nSinh ra MỘT (và chỉ một) hàm Python tên `build_path(points)` trả về QPainterPath.\nCông cụ nhóm này dùng số điểm không cố định: người dùng nhấp chuột trái để thêm\nđiểm, và nhấp chuột phải để kết thúc/commit. Vì vậy metadata BẮT BUỘC là:\n\n    # N_POINTS: -1\n\nINPUT\n=====\n- `points` là `list[QPointF]` gồm toàn bộ các điểm người dùng đã nhấp, theo thứ tự.\n- Khi preview, ứng dụng gọi `build_path(points)` với các điểm đã nhấp + vị trí\n  con trỏ chuột tạm ở cuối danh sách. Khi commit bằng chuột phải, danh sách chỉ\n  gồm các điểm đã nhấp trái, không gồm vị trí chuột phải.\n- Hàm phải xử lý mọi độ dài danh sách:\n    • `len(points) < 2`: trả QPainterPath() rỗng.\n    • Nếu cần ít nhất 3 điểm để khép hình, vẫn có thể preview đoạn hở khi có 2\n      điểm, nhưng commit thiếu điểm nên nên trả rỗng hoặc path hở hợp lý.\n    • Điểm trùng/suy biến: trả QPainterPath() rỗng hoặc bỏ qua điểm trùng, không raise.\n\nOUTPUT\n======\n- Luôn trả về QPainterPath.\n- Nếu mô tả là đường cong tự do, dựng đường mượt đi qua/xấp xỉ toàn bộ điểm.\n- Nếu mô tả là đa giác/hình khép kín, nối các điểm theo thứ tự và gọi\n  `path.closeSubpath()` khi có đủ điểm.\n\nĐỊNH DẠNG ĐẦU RA (BẮT BUỘC)\n===========================\n- Trả về DUY NHẤT một code fence Python:\n  ```python\n  ...\n  ```\n- BA dòng đầu BẮT BUỘC:\n    # NAME: <ten_ngan_khong_dau_cach>      (a-z/A-Z/0-9/_, bắt đầu bằng chữ, ≤ 24 ký tự)\n    # DESC: <ការពិពណ៌នាជាភាសាខ្មែរ 1 បន្ទាត់>\n    # N_POINTS: -1                          ← BẮT BUỘC là -1\n- Sau đó:\n    def build_path(points):\n        ...\n        return path\n- KHÔNG xuất văn bản nào ngoài code fence.\n\nNAMESPACE CÓ SẴN (KHÔNG được import)\n====================================\n- math\n- QPointF, QRectF\n- QPainterPath, QPolygonF, QTransform\n\nCẤM\n===\n- import (bất kể module gì, kể cả `import math`).\n- exec / eval / compile / open / __import__ / globals / locals.\n- Truy cập file, network, subprocess, os, sys, threading, ctypes.\n- Vòng lặp chạy hơn 10 000 lần.\n- Thuộc tính dunder (__xx__).\n\nVÍ DỤ MẪU\n=========\n\nVí dụ 1 — Đa giác\n```python\n# NAME: free_polygon\n# DESC: Đa giác\n# N_POINTS: -1\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    path.moveTo(points[0])\n    for pt in points[1:]:\n        path.lineTo(pt)\n    if len(points) >= 3:\n        path.closeSubpath()\n    return path\n```\n\nVí dụ 2 — Đường cong\n```python\n# NAME: freehand_sketch\n# DESC: Đường cong\n# N_POINTS: -1\ndef build_path(points):\n    path = QPainterPath()\n    if len(points) < 2:\n        return path\n    if len(points) == 2:\n        path.moveTo(points[0])\n        path.lineTo(points[1])\n        return path\n    path.moveTo(points[0])\n    for i in range(len(points) - 1):\n        p0 = points[max(0, i - 1)]\n        p1 = points[i]\n        p2 = points[i + 1]\n        p3 = points[min(len(points) - 1, i + 2)]\n        cp1x = p1.x() + (p2.x() - p0.x()) / 6.0\n        cp1y = p1.y() + (p2.y() - p0.y()) / 6.0\n        cp2x = p2.x() - (p3.x() - p1.x()) / 6.0\n        cp2y = p2.y() - (p3.y() - p1.y()) / 6.0\n        path.cubicTo(QPointF(cp1x, cp1y), QPointF(cp2x, cp2y), p2)\n    return path\n```\n'.strip()

def get_prompt_header(tool_type: str = 'curve') -> str:
    """Trả về system prompt phù hợp với nhóm công cụ."""
    if tool_type == 'line':
        return PROMPT_HEADER_LINE
    if tool_type == 'geometry':
        return PROMPT_HEADER_GEOMETRY
    if tool_type == 'polygon':
        return PROMPT_HEADER_POLYGON
    if tool_type == 'free':
        return PROMPT_HEADER_FREE
    return PROMPT_HEADER_CURVE


_SAFE_BUILTINS = {
    'abs': abs,
    'min': min,
    'max': max,
    'sum': sum,
    'len': len,
    'range': range,
    'enumerate': enumerate,
    'zip': zip,
    'reversed': reversed,
    'sorted': sorted,
    'any': any,
    'all': all,
    'int': int,
    'float': float,
    'round': round,
    'pow': pow,
    'list': list,
    'tuple': tuple,
    'dict': dict,
    'set': set,
    'bool': bool,
    'str': str,
    'True': True,
    'False': False,
    'None': None,
    'isinstance': isinstance,
}

_FORBIDDEN_RE = re.compile(
    r'\b(?:import|from\s+\w+\s+import|__\w+__|open|exec|eval|compile|globals|locals|vars|getattr|setattr|delattr|breakpoint|input|exit|quit|subprocess|sys|socket|urllib|requests|pathlib|threading|ctypes|shutil|tempfile)\b'
)


def _make_sandbox_globals() -> dict:
    return {
        '__builtins__': _SAFE_BUILTINS,
        'math': math,
        'QPointF': QPointF,
        'QRectF': QRectF,
        'QPainterPath': QPainterPath,
        'QPolygonF': QPolygonF,
        'QTransform': QTransform,
    }


def extract_code(raw: str) -> str:
    text = (raw or '').strip()
    m = re.search(r'```(?:python|py)?\s*\n(.+?)\n```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    if text.startswith('```'):
        parts = text.split('```')
        if len(parts) >= 3:
            return parts[1].strip()
    return text


_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,23}$')


def _parse_metadata(code: str) -> tuple[str, str, int]:
    name = ''
    desc = ''
    n_points = 2
    for line in code.splitlines()[:10]:
        s = line.strip()
        if not s.startswith('#'):
            if s and not s.startswith('"""'):
                break
            continue
        s2 = s.lstrip('#').strip()
        upper = s2.upper()
        if upper.startswith('NAME:'):
            name = s2[5:].strip()
        elif upper.startswith('DESC:'):
            desc = s2[5:].strip()
        elif upper.startswith('N_POINTS:'):
            try:
                m_n = re.search(r'-?\d+', s2[9:])
                raw_n = int(m_n.group(0)) if m_n else 2
                n_points = -1 if raw_n == -1 else max(2, min(10, raw_n))
            except (ValueError, TypeError):
                n_points = 2
    return name, desc, n_points


def _check_forbidden(code: str) -> None:
    m = _FORBIDDEN_RE.search(code)
    if m:
        raise ValueError(f'Mã sinh ra chứa từ khoá bị cấm: {m.group(0)}. Hãy yêu cầu lại với mô tả khác.')


def compile_curve_tool(raw_or_code: str) -> dict:
    """Phân tích phản hồi → trả dict {name, description, n_points, code, fn}.

    Ném ValueError nếu code không hợp lệ hoặc test thử thất bại.
    """
    code = extract_code(raw_or_code).strip()
    if not code:
        raise ValueError('Phản hồi rỗng từ Gemini.')
    _check_forbidden(code)
    name, desc, n_points = _parse_metadata(code)
    if not name:
        raise ValueError('Thiếu metadata `# NAME: ...` ở đầu khối mã.')
    if not _NAME_RE.match(name):
        raise ValueError(f"Tên công cụ '{name}' không hợp lệ (cần a-z/A-Z/0-9/_, ≤ 24 ký tự, bắt đầu bằng chữ).")

    sandbox = _make_sandbox_globals()
    locals_dict = {}
    try:
        compiled = compile(code, f'<ai-curve:{name}>', 'exec')
        exec(compiled, sandbox, locals_dict)
    except SyntaxError as exc:
        raise ValueError(f'Lỗi cú pháp Python: {exc.msg} (dòng {exc.lineno}).') from exc
    except Exception as exc:
        raise ValueError(f'Không nạp được mã: {exc}') from exc

    fn = locals_dict.get('build_path') or sandbox.get('build_path')
    if not callable(fn):
        raise ValueError('Mã không định nghĩa hàm `build_path(points)`.')

    _dummy_pts = [
        QPointF(0.0, 0.0),
        QPointF(120.0, 80.0),
        QPointF(60.0, -40.0),
        QPointF(200.0, 150.0),
        QPointF(300.0, 100.0),
        QPointF(250.0, 350.0),
        QPointF(50.0, 400.0),
        QPointF(500.0, 500.0),
    ]
    if n_points == -1:
        _test_cases = [
            _dummy_pts[:6],
            _dummy_pts[:2],
            [QPointF(50.0, 50.0)] * 4,
        ]
    else:
        _test_cases = [
            _dummy_pts[:n_points],
            _dummy_pts[:max(1, n_points - 1)],
            [QPointF(50.0, 50.0)] * n_points,
        ]

    for pts in _test_cases:
        try:
            out = fn([QPointF(p) for p in pts])
        except Exception as exc:
            raise ValueError(f'Hàm build_path ném lỗi khi chạy thử ({len(pts)} điểm): {exc}') from exc
        if not isinstance(out, QPainterPath):
            raise ValueError(f'build_path phải trả về QPainterPath, nhận được {type(out).__name__}.')

    return {
        'name': name,
        'description': desc,
        'n_points': n_points,
        'code': code,
        'fn': fn,
    }


def call_gemini_for_tool(
    api_key: str,
    model: str,
    user_prompt: str,
    log: Callable[[str], None] | None = None,
    tool_type: str = 'curve',
    temperature: float = 0.2,
    timeout_ms: int = 30000,
) -> str:
    if log is None:
        log = lambda _m: None
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError('Thiếu thư viện google-genai. Hãy chạy: pip install google-genai') from exc

    if not (api_key or '').strip():
        raise ValueError('Thiếu khoá API Gemini.')
    if not (user_prompt or '').strip():
        raise ValueError('Mô tả công cụ không được trống.')

    from core.gemini_models import get_candidate_models, is_fallback_error
    candidates = get_candidate_models(model)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    full_prompt = get_prompt_header(tool_type) + '\n\nMÔ TẢ CÔNG CỤ TỪ NGƯỜI DÙNG:\n' + user_prompt.strip()
    last_err = None

    for m_idx, current_model in enumerate(candidates):
        is_last = (m_idx == len(candidates) - 1)
        try:
            log(t('Gọi Gemini ({model})...', model=current_model))
            resp = client.models.generate_content(
                model=current_model,
                contents=[full_prompt],
                config=types.GenerateContentConfig(temperature=temperature),
            )
            text = resp.text or ''
            log(t('✓ Nhận {count} ký tự từ Gemini.', count=len(text)))
            return text
        except Exception as exc:
            last_err = exc
            err_msg = str(exc)
            log(f"Gemini {current_model} error: {err_msg[:120]}")
            if is_fallback_error(exc) and not is_last:
                next_model = candidates[m_idx + 1]
                log(f"→ Tự động chuyển sang: {next_model} …")
                continue

    if last_err:
        raise last_err
    return ''


class CurveToolWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, api_key: str, model: str, prompt: str, tool_type: str = 'curve'):
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._prompt = prompt
        self.tool_type = tool_type

    def run(self):
        try:
            log = lambda m: self.log.emit(str(m))
            raw = call_gemini_for_tool(
                self._api_key, self._model, self._prompt, log, tool_type=self.tool_type
            )
            log(t('Phân tích & nạp mã...'))
            tool = compile_curve_tool(raw)
            if self.tool_type == 'free' and int(tool.get('n_points', 0)) != -1:
                raise ValueError('Công cụ nhóm Tự do phải khai báo `# N_POINTS: -1`.')
            log(t("✓ Công cụ '{tool_name}' sẵn sàng.", tool_name=tool['name']))
            self.finished.emit(tool)
        except Exception as exc:
            tb = traceback.format_exc(limit=3)
            self.log.emit(t('Lỗi: {error}', error=exc))
            self.failed.emit(f'{exc}\n\n{tb}')


def start_curve_tool_worker(parent: QObject, worker: CurveToolWorker) -> QThread:
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
