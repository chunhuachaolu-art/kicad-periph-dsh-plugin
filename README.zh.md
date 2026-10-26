# pcb-periph-dsh（中文）

一个面向 CI 的无头 KiCad 设计检查桥接工具：封装 `kicad-cli` 的
DRC/ERC，输出**规范化的 JSON** 违规计数与
**对 CI 友好的退出码**，用零依赖的 s 表达式读取器把
`.kicad_pcb` 文件解析为**通用净表 JSON**（层、封装、
焊盘、网络、差分对候选），并依据 KiCad 手册记载的后缀
约定**检查差分对命名**。没有 MCP 服务器，不需要运行中的
工程应用，也没有 GUI——只有一条可以放进任何流水线的
命令行。

- Python >= 3.13，仅标准库（零运行时依赖）
- `drc`/`erc` 适用于任何自带 `kicad-cli` 的 KiCad（针对
  KiCad 10.0.5 开发并锁定）；`netlist` 和 `diffpair`
  **完全不需要 KiCad**

## 安装 / 运行

```
# create the project virtual environment (any Python >= 3.13)
python -m venv venv
venv/Scripts/python -m pcb_periph --help      # Windows
venv/bin/python -m pcb_periph --help          # POSIX
```

### kicad-cli 探测

可执行文件按以下顺序探测；第一个实际存在的候选者生效，
而显式指定的候选者若不存在则属于硬性配置错误
（退出码 2）——不会静默回落：

1. `--kicad-cli PATH` 命令行选项
2. `KICAD_CLI` 环境变量
3. 内置回落位置 `F:\kicad\bin\kicad-cli.exe`
4. 在 `PATH` 上找到的 `kicad-cli`

### 板级上下文敏感性（重要）

对**裸 `.kicad_pcb`** 运行 DRC 时，应用的是板文件内嵌的
约束集（或 KiCad 默认值）；对属于**完整工程**的板
（其目录中存在 `.kicad_pro`）运行时，则改为加载
该工程的约束集——包括 DRC 严重级别覆盖。同一块板在两种
模式下报告出差别很大的违规计数是完全合法的——例如
`diffpair_showcase` 示例板在 KiCad 10.0.5 上测得
**作为完整工程 0 项违规、作为裸文件 14 项警告**
（工程上下文忽略 `lib_footprint_issues` 检查，因为该示例
未随附其源封装库；开发期间在一块第三方板上观察到
反方向的同一效应：裸文件 69 项违规、完整工程中 0 项）。
请选择与所需检查相匹配的输入；
批处理模式两者皆可。

`netlist` **不受**这一区别影响：净表完全存在于
`.kicad_pcb` 文件内部，因此裸板副本解析出的净表内容
与其完整工程目录中的板完全一致（由一个显式测试覆盖）。
不读取 `.kicad_pro`、`.kicad_prl`，也不读取任何
工程上下文。

## 用法

```
pcb-periph-dsh drc [--out FILE] [--raw-dir DIR] [--canonical]
                   [--runs N] [--timeout SECONDS] [--kicad-cli PATH]
                   BOARD [BOARD ...]

pcb-periph-dsh erc [same options] SCHEMATIC [SCHEMATIC ...]

pcb-periph-dsh netlist [--out FILE] [--canonical]
                       [--diffpair-rules NAME]
                       BOARD [BOARD ...]

pcb-periph-dsh diffpair (--netlist FILE | --board BOARD)
                        [--out FILE] [--canonical]
```

示例：

```
# single board, JSON to stdout
python -m pcb_periph drc myboard.kicad_pcb

# batch, canonical JSON to a file, raw reports kept next to it
python -m pcb_periph drc a.kicad_pcb b.kicad_pcb \
    --out reports/drc.json --canonical

# schematic ERC with a three-run stability check
python -m pcb_periph erc top.kicad_sch --runs 3 --out reports/erc.json

# typical CI gate
pcb-periph-dsh drc board.kicad_pcb --canonical --out drc.json \
    && echo "clean" || echo "DRC findings or error (see drc.json)"

# netlist extraction (no KiCad installation needed at all)
python -m pcb_periph netlist board.kicad_pcb --canonical --out netlist.json

# differential-pair check: straight from a board file...
python -m pcb_periph diffpair --board board.kicad_pcb

# ...or from a netlist JSON produced above
python -m pcb_periph diffpair --netlist netlist.json --canonical --out dp.json
```

### 选项

| 选项 | 含义 |
|---|---|
| `--out FILE` | 将 JSON 报告写入 `FILE` 而非 stdout |
| `--raw-dir DIR` | 存放 kicad-cli 原始 JSON 报告的目录（默认：`--out` 所在目录，否则为工作目录） |
| `--canonical` | 输出规范化形态（剥离易变字段）——见*确定性* |
| `--runs N` | 对每个输入运行 kicad-cli N 次并记录所有运行是否产生相同计数（默认 1） |
| `--timeout SECONDS` | 单次运行的 kicad-cli 超时（默认 600） |
| `--kicad-cli PATH` | 显式指定的 kicad-cli 可执行文件路径 |

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 未发现违规（未连接项同样为零） |
| 1 | 发现违规（含未连接项） |
| 2 | 工具或配置错误：kicad-cli 未找到/失败、输入后缀错误、选项无效 |
| 3 | 输入文件不可读：缺失、不是常规文件、无读取权限 |

给定多个输入时，取最差结果：
`3 (unreadable) > 2 (tool/config) > 1 (violations) > 0`。

## 输出 JSON schema（`schema_version` 1.0.0）

`drc` 输出：

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "drc",
  "kicad_version": "10.0.5",
  "boards": [
    {
      "status": "ok",
      "board": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
      "raw_report": "out/demo/diffpair_showcase.drc-raw.json",
      "violations": {
        "total": 25,
        "by_severity": { "error": 25 },
        "by_type": { "clearance": 25 }
      },
      "unconnected": 0,
      "ignored_checks": 6
    }
  ],
  "summary": { "boards": 1, "boards_ok": 1, "violations": 25, "unconnected": 0 },
  "timing_ms": 6100
}
```

（上面的摘录是把 showcase 示例的最小间距提高到
5 mm 后的版本——即由 `tests/make_dirty_fixture.py` 构建的
“脏板”；未改动的板报告 0 项违规）

`erc` 输出相同结构，但条目为 `schematics[]`；
每个条目以 `sheets` 计数取代 `unconnected`，
且违规按原理图的全部页聚合。

字段说明：

- **分桶仅使用 kicad-cli 的原生分类。** `by_severity` 与
  `by_type` 按 kicad-cli 报告的 `severity`/`type`
  字符串原样计数（例如 `error`、`warning`；`clearance`、
  `copper_edge_clearance`、`lib_footprint_issues`）。
  不做派生分类，不做重新解读——要查看位置与完整细节，
  请读取 `raw_report` 所引用的原始报告。

- **路径锚定。** `board` 与 `raw_report` 是相对进程
  工作目录的正斜杠路径；若路径无法相对化
  （例如 Windows 上盘符不同），则改为记录
  绝对路径。

- **失败的输入保留在载荷中。** 不可用的输入以
  `{"status": "unreadable" | "config_error" | "tool_error", "error": "..."}`
  的形式出现，而非 `ok` 条目，且退出码反映最差状态。

## 净表提取（`netlist`）

`netlist` 用净室实现、纯标准库的 s 表达式读取器解析
`.kicad_pcb` 文件，并输出**通用净表 JSON**——不需要
`kicad-cli`、不需要安装 KiCad、不涉及工程上下文。读取
`diffpair_showcase` 示例板耗时远低于 0.1 s；约 900 KB 的
第三方板约需 0.4 s。

| 选项 | 含义 |
|---|---|
| `--out FILE` | 将 JSON 报告写入 FILE 而非 stdout |
| `--canonical` | 输出规范化形态（剥离易变字段）——见*确定性* |
| `--diffpair-rules NAME` | 用于候选扫描的差分对后缀规则集（默认 `kicad-doc-v1`，即 KiCad PCB 编辑器手册所记载、并与 `diffpair` 命令共用的规则集；`none` 禁用） |

退出码：`0` 所有板解析成功，`2` 配置错误（输入后缀错误、
无法作为 `.kicad_pcb` s 表达式解析），`3` 输入文件不可读。
没有“发现违规”退出码——这是一个读取器，不是检查器。
给定多个输入时，取最差结果（`3 > 2 > 0`），不可用的输入
以带 `status` 与 `error` 的条目保留在载荷中，而非 `ok` 条目。

### 输出 JSON schema（`schema_version` 1.0.0）

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "netlist",
  "diffpair_rule_set": "kicad-doc-v1",
  "boards": [
    {
      "status": "ok",
      "board": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
      "source": { "version": 20241229, "generator": "pcbnew",
                  "generator_version": "9.0" },
      "layers": [
        { "index": 0, "name": "F.Cu", "type": "signal" }
      ],
      "footprints": [
        { "reference": "R2", "library_id": "Generated:R_pair_0603",
          "layer": "F.Cu", "position": { "x": 30, "y": 35 }, "pads": 2 }
      ],
      "pads": [
        { "footprint": "R2", "pad": "1", "type": "smd",
          "shape": "rect", "net": { "id": 3, "name": "DATA_P" } }
      ],
      "nets": { "GND": ["R6-2", "R7-2", "R8-2", "R9-2", "R10-2", "J1-2", "C1-2"] },
      "pads_no_net": 1,
      "diffpair_candidates": {
        "rule_set": "kicad-doc-v1",
        "suffix_groups": [ { "group": "plus_minus", "suffix_style": "symbol",
                             "positive_suffix": "+", "negative_suffix": "-" },
                           { "group": "p_n", "suffix_style": "separator",
                             "positive_suffix": "P", "negative_suffix": "N",
                             "separators": ["_", "-", "."] },
                           { "group": "p_n", "suffix_style": "bare",
                             "positive_suffix": "P", "negative_suffix": "N" } ],
        "pairs": [ { "base": "CLK", "positive": "CLK-P", "negative": "CLK-N",
                     "pads": { "positive": 1, "negative": 1 }, "...": "group/style/suffixes" } ],
        "unpaired": [ { "net": "PIEZO_IN", "base": "PIEZO_I",
                        "polarity": "negative", "suffix_style": "bare", "...": "group/separator/suffix/pads" },
                      { "net": "SENSE+", "...": "symbol-style positive half" } ]
      },
      "stats": { "layers": 20, "footprints": 14, "pads": 27,
                 "pads_no_net": 1, "pads_with_net": 26,
                 "nets_declared": 20, "nets_named": 19,
                 "diffpair_pairs": 5, "diffpair_unpaired": 5,
                 "diffpair_suspicious": 2 }
    }
  ],
  "summary": { "boards": 1, "boards_ok": 1, "...": "sums of all stats keys" },
  "timing_ms": 147
}
```

字段说明：

- **`layers`** 条目原样携带板的 `(layers ...)` 节点中声明的
  铜层/技术层的 `index`、`name` 与 `type`，
  外加可选的用户昵称。
- **`pads`** 是按文件顺序的扁平列表；`type` 为焊盘工艺
  （`thru_hole`、`smd` 等），`shape` 为焊盘形状（`rect`、`oval` 等）。
- **`net`** 对无网络的焊盘为 `null`；引用未命名网络 0
  或空网络名的焊盘同样计为无网络。
- **`nets`** 将每个*已命名*网络按文件顺序映射到其
  `"REF-PAD"` 引用列表；`pads_no_net` 统计其余焊盘。
  自动生成的 `unconnected-(...)` 网络在本工具一侧和
  KiCad 自家读取器一侧都是普通的已命名网络。
- **`diffpair_candidates`** 是仅对已命名网络做的名字后缀
  扫描——与 `diffpair` 子命令使用同一引擎（规则集
  `kicad-doc-v1`，完整规则语义与锁定的边界决策见下文
  *差分对检查*一节）。**变更说明：**在 `diffpair` 命令
  出现之前，该扫描使用最小化的 `basic` 规则集（仅 `+`/`-`
  与 `_P`/`_N`）；检查器落地时默认切换为手册记载的完整
  约定集，因此带有 `diffpair_rule_set: "basic"` 的旧输出
  早于这一变更。`pairs`/`unpaired` 携带基础名、极性与
  焊盘计数；`unpaired` 列出对端缺失的带后缀网络——
  在完整约定集下这包括裸 P/N 名字，例如示例板的
  `SENSE+` 符号风格半边**以及**其 `PIEZO_IN` 网络
  （一个裸 `N` 半边，基础名 `PIEZO_I`）。形如
  `Net-(U201B-+)` 的自动生成名字以 `)` 结尾，因此
  不带后缀。Python API 提供同一套规则集
  （`pcb_periph.diffpair.RULE_SETS`、`check_diffpairs`），
  另有一个仅按名字的适配器
  （`pcb_periph.netlist.scan_diffpairs`）。
- **`stats`** 计数与载荷内容一致（焊盘列表之和 =
  `pads_with_net` 等），`summary` 块则对所有板求和。
- **确定性**与 `drc`/`erc` 完全一致：无时间戳，唯一易变字段
  为 `timing_ms`，同一输入+选项+工作目录的多次运行产出
  字节级一致的规范化形态——示例板的冒烟摘要为
  `sha256: 8933a0dd847179c6...`（前 16 个十六进制字符，
  针对 KiCad 10.0.5 解析的输入锁定）。

**交叉验证：**解析器输出在测试套件中与 KiCad 自带的
`pcbnew` 读取器核对（封装/焊盘/网络计数以及完整的
焊盘到网络映射）。该比对仅是开发侧的辅助设施——
采用 GPL 许可的 `pcbnew` 模块只被一个测试脚本导入，
绝不会被发布的包导入；后者的解析器为净室实现
且零依赖。

## 差分对检查（`diffpair`）

`diffpair` 将一块板的已命名网络与 KiCad PCB 编辑器手册
记载的差分对命名约定（规则集 **`kicad-doc-v1`**）做
配对检查，报告完整对、未配对半边与可疑的近配对名字——
并附上取自净表的每网络焊盘计数，因此两网络焊盘计数
悬殊的“对”很容易被发现。纯名字检查：不需要
`kicad-cli`、不需要安装 KiCad、不涉及工程上下文。

两条输入路径，每次调用必须恰好给出一条
（二者互斥）：

- `--board BOARD.kicad_pcb`——先通过 `netlist` 管线解析该板，
  再检查；
- `--netlist FILE`——从 `netlist` 子命令的 JSON 报告读取网络
  （必须恰好包含一块成功解析的板；该报告的
  规范化形态也是合法输入）。

两条路径产出相同的检查结果（由一个显式测试覆盖）。

| 选项 | 含义 |
|---|---|
| `--netlist FILE` | 从 netlist 子命令的 JSON 报告读取网络 |
| `--board BOARD` | 从 `.kicad_pcb` 文件读取网络（先走 netlist 管线） |
| `--out FILE` | 将 JSON 报告写入 FILE 而非 stdout |
| `--canonical` | 输出规范化形态（剥离易变字段）——见*确定性* |

退出码：`0` 检查完成——**零配对的板同样算完成的检查**，
未配对半边或可疑发现不会改变退出码；`2` 输入/配置错误
（JSON 无效、不是净表文档、后缀错误、无法作为
`.kicad_pcb` s 表达式解析）；`3` 输入文件不可读。
若要按发现项判定失败，请以 JSON 字段为门控依据，
而不是退出码。

### 输出 JSON schema（`schema_version` 1.0.0）

```json
{
  "schema_version": "1.0.0",
  "tool": "pcb-periph-dsh",
  "tool_version": "0.1.0",
  "command": "diffpair",
  "status": "ok",
  "rule_set": "kicad-doc-v1",
  "suffix_groups": [ { "group": "plus_minus", "suffix_style": "symbol",
                       "positive_suffix": "+", "negative_suffix": "-" },
                     { "group": "p_n", "suffix_style": "separator",
                       "positive_suffix": "P", "negative_suffix": "N",
                       "separators": ["_", "-", "."] },
                     { "group": "p_n", "suffix_style": "bare",
                       "positive_suffix": "P", "negative_suffix": "N" } ],
  "input": { "kind": "board", "path": "examples/diffpair_showcase/diffpair_showcase.kicad_pcb",
             "source": { "version": 20241229, "generator": "pcbnew",
                         "generator_version": "9.0" } },
  "pairs": [
    { "base": "CLK", "positive": "CLK-P", "negative": "CLK-N",
      "group": "p_n", "suffix_style": "separator", "separator": "-",
      "suffixes": { "positive": "-P", "negative": "-N" },
      "pads": { "positive": 1, "negative": 1 }, "pads_total": 2 }
  ],
  "unpaired": [
    { "net": "LONE_P", "base": "LONE", "polarity": "positive",
      "group": "p_n", "suffix_style": "separator", "separator": "_",
      "suffix": "_P", "pads": 1 }
  ],
  "suspicious": [
    { "kind": "suffixless_twin", "base": "DATA", "net": "DATA",
      "suffix_nets": ["DATA_N", "DATA_P"] }
  ],
  "stats": { "nets_named": 19, "pairs": 5, "nets_in_pairs": 10,
             "unpaired": 5, "suspicious": 2, "pads_in_pairs": 10,
             "pads_in_unpaired": 5 },
  "timing_ms": 402
}
```

字段说明：

- **`pairs`** 是完整对：共同基础名、两个网络名、匹配到的
  后缀组/风格、实际后缀字符串与每侧焊盘计数。
  按基础名排序。
- **`unpaired`** 是对端缺失的带后缀网络——网络、基础名、
  极性（`positive`/`negative`）、分解结果与焊盘计数。
  按网络名排序。
- **`suspicious`** 列出可机械判定的近配对线索：
  `suffixless_twin`（一个普通网络的名字恰好等于某些带后缀
  网络的基础名，例如 `DATA_P`/`DATA_N` 旁边的 `DATA`）与
  `mixed_suffix_style`（两个或更多未配对半边共享同一基础名
  但后缀字符串不同，例如 `DATA_P` 旁边是 `DATA-N`、
  `DATA_P` 旁边是 `DATAN`，或 `DATA_P` 旁边是 `DATA+`）。
- **`input`** 记录来源信息：`kind`（`board`/`netlist`）、
  相对工作目录的路径锚定、板源文件头（已知时），
  以及——对 `netlist` 类型而言——板锚定与净表报告的
  `schema_version`。
- 不可用的输入产出 `{"status": "unreadable" | "config_error", "error": "..."}`
  而非检查字段，退出码为 3/2。
- **确定性**与其他地方一致：无时间戳，唯一易变字段为
  `timing_ms`；固定输入+选项+工作目录的规范化形态在
  多次运行间字节级一致（示例板经 `--board` 的冒烟摘要：
  `sha256: baf24005afa1757b...`，前 16 个十六进制字符；
  `--netlist` 路径产出相同的 pairs/unpaired/suspicious/stats，
  其摘要额外取决于净表报告自身的存放位置）。

### 规则集 `kicad-doc-v1`

该规则集是对 KiCad 10.0 PCB 编辑器手册中网络命名约定的
净室实现（[Differential pairs](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#differential_pairs)，
*Board setup → Differential pairs*；措辞以 KiCad 10.0 为准）：

> "Differential pairs in KiCad are defined as nets with a common base
> name and a positive and negative suffix. KiCad supports using + and −,
> or P and N as the suffixes."

实现为两个后缀组，始终位于网络名的**末尾**：

| 组 | 风格 | 正极后缀 | 负极后缀 | 示例对 |
|---|---|---|---|---|
| `plus_minus` | `symbol` | `+` | `-` | `CLK+` / `CLK-` |
| `p_n` | `separator` | `P`（跟在 `_`、`-` 或 `.` 之后） | `N`（跟在 `_`、`-` 或 `.` 之后） | `DATA_P` / `DATA_N` |
| `p_n` | `bare` | `P` | `N` | `DATAP` / `DATAN` |

当两个网络共享**同一基础名**、同一组**且**同一风格
（同一分隔符字符）时，才报告为一个对。手册对若干
边界未作规定；以下选择由测试（`tests/test_diffpair.py`）
锁定，并属于规则集契约的一部分：

| 边界 | 锁定选择 | 理由 / 效果 |
|---|---|---|
| 大小写敏感性 | 大小写敏感：仅大写 `P`/`N` 有效 | 手册写明 “P and N”；`DATA_p`/`DATA_n` 既不配对也不作为半边出现 |
| `P`/`N` 的分隔符集合 | 恰为 `_`、`-`、`.` | 三个惯用分隔符，无其他；`DATA=P` 不带后缀 |
| 同一对内分隔符混用 | 不配对 → `mixed_suffix_style` 可疑 | `DATA_P` 旁边是 `DATA-N` 属于命名不一致，检查器应当揭示而非吸收 |
| 同一基础名内风格混用 | 不配对 → `mixed_suffix_style` 可疑 | `DATA_P` 旁边是 `DATAN`、或 `DATA_P` 旁边是 `DATA+` 时同理 |
| 多级后缀 | 仅在最后一层分解 | `USB_DP`/`USB_DN` 在基础名 `USB_D` 上配对（裸风格） |
| `+`/`-` 出现在名字中间 | 绝不算后缀 | `DATA+CLK` 不带后缀；后缀仅在名字末尾处绑定 |
| 空基础名 | 不带后缀 | 单独的 `+`、`-`、`P`、`N` 被忽略；`_P` 回落到裸风格（基础名 `_`） |
| 基础名以分隔符+符号结尾 | 基础名保留分隔符 | `CLK_+`/`CLK_-` 在基础名 `CLK_` 上配对（符号组只取最后一个字符） |
| 符号为 ASCII | 仅 `+` 与 `-` | 手册行文中的排版符号 `−` 不是网络名字符 |
| 裸 P/N 误报 | 接受，但打上标记 | 任何以 `P`/`N` 结尾的网络都带后缀，因此词尾字母可构成半边（示例板的 `PIEZO_IN` 网络即基础名 `PIEZO_I` 上的裸 `N` 半边）；每个条目都带 `suffix_style`，因此 `bare` 发现项可轻易过滤 |

`netlist` 子命令上的 `--diffpair-rules` 使用同一规则集
（默认 `kicad-doc-v1`，`none` 禁用）；
`netlist` 报告中的 `diffpair_candidates` 块
是同一引擎按板内嵌的结果。

## 确定性、规范化形态与哈希

载荷中**不含时间戳**。唯一的易变字段是顶层的 `timing_ms`。
**规范化形态**是去掉易变字段后的载荷，以排序键、
UTF-8 与 LF 行尾序列化：

- `--canonical` 直接写出该形态；
- 事后处理：`pcb_periph.canonical.dumps_canonical(json.load(report))`
  可逐字节复现它。

对固定的输入、固定的 kicad-cli 版本、固定的选项与固定的
工作目录，两次运行产出**字节级一致的规范化 JSON**——
这是“固定输入 → 固定 sha256”冒烟测试的基础：

```
python -m pcb_periph drc board.kicad_pcb --canonical --out a.json
python -m pcb_periph drc board.kicad_pcb --canonical --out b.json
sha256sum a.json b.json        # identical digests
```

**上游注意事项（如实的局限）：**

- `kicad-cli` 10.0.5 本身对含有大量近阈值几何对的板并非
  完全确定——违规*集合*可能在运行间略有差异（在一块
  刻意收紧规则的测试板上观察到 ±1…3 的计数波动），
  与本工具无关。规范化形态保证本工具所添加的一切
  内容字节稳定；上游计数漂移时，那就是漂移。请使用
  `--runs N`（配合每板的
  `stable` 标志）显式检测此类漂移，
  而不要信任单次运行。

- `kicad-cli` 在某些运行中会在输入旁写入
  `<project>.kicad_prl` 设置文件；这是 kicad-cli 的行为，
  本工具无法抑制。请把输入目录视为可被流水线写入。

## 为什么不用 kicad-mcp-pro 的 `run_drc`？

[kicad-mcp-pro](https://github.com/lakbubuaa/kicad-mcp-pro) 4.3.0 以 MCP
工具的形式暴露 `run_drc`。本 CLI 的差异是有意为之：

1. **CLI 优先，CI 原生。**没有 MCP 服务器、没有 Python-MCP
   运行时、也没有需要连接的活动工程/应用上下文——一个进程、
   一条命令、一份输出到 stdout 或文件的 JSON 文档。可直接
   嵌入任何 CI 运行器、cron 任务或 shell 脚本。
2. **规范化、带 schema 版本的输出。**违规计数按原生
   severity/type 分桶、路径锚定、kicad 版本、由
   `schema_version` 门控的 schema——而非原始报告的透传。
   原始报告仍被保留并引用，以供查看完整细节。
3. **对 CI 友好的退出码**（上文的 0/1/2/3）且优先级有明文
   规定，因此流水线门控只需一次 shell 判定。
4. **可移植的 kicad-cli 探测**——环境变量覆盖与多位置探测，
   而非硬编码的安装路径。
5. **多板批处理运行**，单次调用完成，带每板状态条目
   与汇总块。
6. **可配置的多次运行稳定性检查**（`--runs N` + `stable`
   标志），显式呈现 kicad-cli 的运行间漂移。

对 `netlist` 而言，上游的对比对象是 `pcb_get_board_summary`
（一个摘要视图，而非净表）：本 CLI 输出完整的焊盘级净表
（`net → pad references`、焊盘到网络映射）、差分对候选，
以及字节稳定的规范化 JSON——零运行时依赖，且完全
不需要安装 KiCad。

对 `diffpair` 而言，上游没有对比对象：kicad-mcp-pro 4.3.0
不带差分对配对检查器（其 `sch_get_connectivity_graph` 是
原理图连通图，不是 PCB 净表配对检查）。本 CLI 补上了按
手册后缀的配对审计，带未配对/可疑发现、焊盘计数以及
相同的规范化 JSON/退出码契约。

## 示例板（测试数据）

`examples/` 下的所有板都是**原创的脚本生成内容**，由本
仓库的生成器 `tests/make_boards.py` 写出（确定性：
重新生成可逐字节复现这些文件）。它们不含第三方版权，
随仓库以 MIT 许可发布且无署名要求——这正是它们存在的
原因：在 MIT 仓库中再分发 KiCad 自带的演示板会造成
许可不匹配（KiCad 演示集合为 CC BY-SA 4.0），因此
测试套件与示例共用同一组生成板。

- `examples/diffpair_showcase/`——一块两层板，其 19 个
  已命名网络演练了 `kicad-doc-v1` 约定的每一种后缀风格：
  五个完整对（`CLK+`/`CLK-`、`DATA_P`/`DATA_N`、
  `CLK-P`/`CLK-N`、`USB.P`/`USB.N`、多级裸风格的
  `USB_DP`/`USB_DN`）、五个未配对半边、一个
  `suffixless_twin`、一个 `mixed_suffix_style` 发现，以及
  一个 `+` 在中间的阴性对照（`DATA+CLK`）。含一个最小化
  的 `.kicad_sch`（ERC 目标）和一个 `.kicad_pro`——内含
  KiCad 默认设计规则外加一项严重级别覆盖
  （`lib_footprint_issues` 在工程上下文中被忽略，因为这块
  自包含的板未随附其源封装库）。
- `examples/small_mcu/`——第二块更朴素的板（连接器、无源
  器件、一对 `DM_P`/`DM_N`、一个未配对的 `SW_N` 半边）。

**脏 DRC 夹具不随仓库发布**：测试用 `tests/make_dirty_fixture.py`
在临时目录中即时构建它——该脚本复制 showcase 工程并在复制出的
`.kicad_pro` 中把 `min_clearance` 提高到 5 mm，从而产生大量
真实的 `clearance` 违规（KiCad 10.0.5 上为 25 项）。
干净的示例板从不被修改。

## 开发

```
venv/Scripts/python tests/make_boards.py           # regenerate example boards
venv/Scripts/python tests/run_tests.py             # stdlib test runner
python -m pytest tests/                            # equivalent under pytest
venv/Scripts/python tests/audit_engine_isolation.py --source-root /path/to/private/source
```

`tests/make_dirty_fixture.py --src examples/diffpair_showcase --dst DIR`
构建脏板副本（见*示例板*）；测试套件自身会在
临时目录中完成这一步。

测试使用朴素的 pytest 风格函数（`test_*` + 裸 assert），
并要求机器上装有 kicad-cli；找不到时自动跳过。
`tests/run_tests.py` 是面向无法安装 pytest 环境的
零依赖后备运行器。

`tests/test_netlist_crosscheck.py` 另外将 `netlist` 解析器与
KiCad 自带的 `pcbnew` 模块核对；它在 KiCad 解释器下运行
`tests/netlist_pcbnew_probe.py`（默认
`F:\kicad\bin\python.exe`，可用 `$PCBNEW_PYTHON` 覆盖），
在该解释器缺席时跳过。`pcbnew` 采用 GPL 许可，因此只被
那个测试侧探针脚本导入——绝不被 `pcb_periph` 导入。
