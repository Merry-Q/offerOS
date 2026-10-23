---
name: OfferOS
description: 以原文依据、清晰状态和可控操作呈现求职信息的作品集演示。
colors:
  navy: "#102636"
  ink: "#14283a"
  teal: "#087f78"
  paper: "#f6f8f9"
  white: "#fff"
  archive-muted: "#536979"
  global-muted: "#607181"
  line: "#dbe2e7"
  archive-tint: "#eef3f4"
  selected-tint: "#d5eae5"
  evidence-tint: "#f0f7f6"
  teal-tint: "#dff3f0"
  teal-ink: "#0b504f"
typography:
  display:
    fontFamily: '"Source Serif 4", serif'
    fontSize: "33px"
    fontWeight: 700
  brand:
    fontFamily: '"Source Serif 4", serif'
    fontSize: "25px"
    fontWeight: 700
  headline:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.65
  title:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.65
  body:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "13px"
    lineHeight: 1.85
  label:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "12px"
    lineHeight: 1.65
  discovery-title:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.4
  discovery-score:
    fontFamily: '"Noto Sans SC", sans-serif'
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1.3
rounded:
  signal: "4px"
  badge: "5px"
  control: "6px"
  nav: "7px"
  original: "8px"
  global-card: "10px"
  archive-section: "12px"
spacing:
  xs: "6px"
  sm: "8px"
  control: "12px"
  md: "16px"
  field: "20px"
  section: "24px"
components:
  button-teal:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
  button-secondary:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
  input:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  chip:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "999px"
    padding: "6px 12px"
  archive-section:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.archive-section}"
  archive-value:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  discovery-job:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    padding: "24px"
  discovery-signal:
    backgroundColor: "{colors.teal-tint}"
    textColor: "{colors.teal-ink}"
    rounded: "{rounded.signal}"
    padding: "3px 8px"
---

# Design System: OfferOS

## Overview

**Creative North Star: "可核对的求职档案"**

OfferOS 面向作品集演示，用冷静的深蓝外壳、浅灰纸面和节制的青绿操作色呈现 AI 的依据、可靠性与用户控制。信息先可读，再可展开核对；视觉重点来自字号、间距、选中底色和来源提示。

本文按现有代码及桌面、移动截图提取，记录既有身份及简历档案页的扩展。档案页参考 OfferLink 的上传、模块归档和侧边目录组成，沿用 OfferOS 配色与字体；未建立新的品牌身份，也不把这一页的构图推广为所有页面的要求。

匹配岗位页延续同一身份：白色筛选工作区之后是按快速匹配分排列的连续岗位列表。筛选、出站职业标签、招聘原页与评分依据形成可核对的操作链；本节扩展依据 `static/job-discovery.css`、`static/job-discovery.js` 与 `static/index.html`，不改变既有档案规则。

**Key Characteristics:**
- 深蓝导航、浅灰纸面、白色信息模块。
- 青绿聚焦主要操作、当前选择与原文依据。
- 模块信息、来源引用与解析状态分层可读。
- 桌面双栏核对，移动单栏阅读与横向切换。

## Colors

色值以 frontmatter 为准。冷色中性色承担大面积阅读，青绿承担动作与依据提示。

### Primary

- **核对青绿**（`teal`）：上传、岗位分析按钮、来源链接及档案页焦点轮廓。
- **深海蓝**（`navy`）：应用导航外壳与品牌承载区。

### Neutral

- **正文墨蓝**（`ink`）：标题、正文及深色主要按钮。
- **冷灰纸面**（`paper`）与**纯白内容面**（`white`）：页面背景、字段值底色与白色模块的层级关系。
- **档案灰蓝**（`archive-muted`）：档案页标签、说明、行号与空模块状态。全局旧页面保留 `global-muted`，不合并这两个实际存在的值。
- **细线灰**（`line`）：模块边框、页内分隔与输入控件边框。
- **侧栏浅灰青**（`archive-tint`）、**选中浅青**（`selected-tint`）、**引用浅青**（`evidence-tint`）：分别用于简历管理区、选中简历与展开原文。
- **标签浅青**（`teal-tint`）与**依据深青**（`teal-ink`）：匹配岗位页的出站职业标签使用前者作底、后者作字；在招依据与已完成阶段也使用依据深青。它们来自既有页面色值，不替代档案页的浅青色角色。

**The Evidence Accent Rule.** 在档案页，青绿用于可执行操作、当前状态及可核对的来源，不用色彩暗示简历未提供的能力。

## Typography

**Display Font:** Source Serif 4，回退 serif。沿用品牌及原有页面展示标题。

**Body Font:** Noto Sans SC，回退 sans-serif。简历档案页的主标题、模块和字段统一使用这一字体。

**Character:** 衬线字保留品牌识别，无衬线字承担密集中文资料阅读。档案页不沿用其他页面的大号衬线展示标题。

### Hierarchy

- **Display**：原有页面展示标题使用 `display`；品牌使用 `brand`。原有页面在窄屏下将标题调整为（27px）。
- **Headline**：档案页标题使用 `headline`；当前文件名另用（20px），窄屏缩至（18px）。
- **Title**：模块标题使用 `title`；上传区标题同为（16px）。
- **Body**：字段值使用 `body`，保留换行并允许长字符串换行。页面基础行高为（1.65），档案字段单独加宽行距。
- **Label**：标签与辅助说明使用 `label`；引用与行号另缩至（11px）。
- **Matching Jobs**：职位标题使用 `discovery-title`，手机降为（20px）；列表标题同为（21px），筛选区标题为（19px）。快速分使用 `discovery-score`，等宽数字排列，分母为（13px）。元信息值为（13px），字段名与评分说明为（11px）。这些是已实现的局部字号，不推导新的全局比例尺。

## Layout

全局桌面外壳为左导航（216px）加内容区；导航占满视口高度并吸顶。档案内容区宽度上限（1320px），桌面内边距沿用（28px 42px 70px）。上传条在归档内容之前，占满内容宽度。

档案页主体为弹性主栏加右侧管理栏（208px），栏间距（24px）。右栏吸顶偏移（24px），包含简历切换与模块目录。主栏按基本信息、求职期望、教育、工作、实习、项目、技能与语言、证书与获奖、其他简历信息排列；字段默认两列，长内容可跨整行。模块之间（16px），字段之间（20px），模块内容水平内边距（22px）。这些是档案页的构图，不是其他页面的强制模板。

视口不大于（1160px）时，右栏缩为（176px），栏间距（18px），内容水平留白（28px）。不大于（980px）时，右栏移到内容上方并取消吸顶，简历列表和目录改为横向滚动。不大于（760px）时，全局导航改为顶部横向导航，字段改为单列，主区内边距（22px 15px 48px），模块内容内边距（16px），上传条允许换行并隐藏装饰图标。

匹配岗位页沿用全局主区宽度上限（1100px）。筛选区内边距（24px），四列宽度比例为（1.4fr 1fr 1fr 1fr），列间距（14px）；不大于（980px）时变为两列，不大于（540px）时变为单列且内边距收为（18px）。职业标签可换行，搜索按钮与说明在桌面横排，手机纵排；流程阶段在窄屏允许换行。

岗位结果以连续横行承载，左右分别为可伸缩的职位信息与（128px）评分操作栏，间距（25px），每行内边距（24px）。元信息与来源行均可换行，长文本不撑破容器。不大于（540px）时，岗位改为单列，内边距（20px 16px），评分、说明与分析按钮在底部横排；岗位之间以细线分隔，不叠加卡片间距。

## Elevation & Depth

档案模块采用白底、细边框和浅色填充建立层级，没有卡片阴影。原有通用卡片保留 `--shadow`（`0 18px 55px rgba(20,40,58,.08)`）；不要误把它应用到档案模块。右栏以低对比浅灰青整合，不做悬浮面板。

匹配岗位的筛选区、岗位横行和报告来源条同样无阴影；白底、边框、分隔线及浅色职业标签建立层级。

**The Quiet Surface Rule.** 档案页静态信息面保持平整，状态变化通过底色、边框与文本表达。

## Shapes

档案上传条、模块与侧栏使用舒缓圆角（12px）。按钮、输入框与字段值使用更紧的圆角（6px）；状态小标记为（5px）。原文文本容器为（8px），原有通用卡片为（10px），导航项为（7px）。已有建议标签保留胶囊形，不将胶囊形扩展到信息模块。

匹配岗位筛选区沿用通用卡片圆角，职业标签与门槛警告使用紧小圆角（4px）。岗位横行与虚线空态保持方角；报告来源条沿用（8px）圆角。

## Components

### Buttons

按钮以短实心矩形明确表达动作。青绿按钮用于上传与分析，深墨蓝按钮保留给原有主要入口，白底细边框按钮用于查看原文等辅助动作。内边距使用 frontmatter 中的按钮值，字重（600）。禁用状态透明度为（0.45），同时使用不可操作光标。

档案页按钮悬停使用 `brightness(.96)`；键盘焦点为青绿轮廓（3px），偏移（3px）。全局其他页面原有焦点为浅青轮廓（3px），偏移（2px）。

### Inputs / Fields

实际输入控件为白底、细线边框与紧圆角；文本域可垂直调整。档案中浅灰底的字段值是只读信息，不能画成可编辑表单。上传由原生文件控件承接，界面呈现选择按钮、支持格式提示与实时状态文本。

### Navigation

深蓝导航上默认使用浅灰蓝字，当前页以浅青底与深青字识别。档案目录使用低对比文字，悬停或当前项变为浅青底；模块数量保持右对齐。简历选中项用 `selected-tint` 标记，文件名与解析状态分两行。

### Chips

已有建议标签为白底细线胶囊，文字（12px、600）；悬停时边框与文字转为青绿。档案解析状态采用更小的圆角矩形，成功、失败状态分别有文字与色彩提示。

### Cards / Containers

档案模块是可展开的原生 details：标题、信息数量与方向图标同一行；内容区承接两列字段。空模块显示“简历未体现”，保留紧凑标题行，不填造经历。方向图标在展开时旋转（180deg），过渡为（160ms ease-out）；减少动态效果偏好下移除过渡。

### Resume Evidence

每项字段先展示标签和值，再提供可展开的“原文依据”与文本行号；展开后显示浅青底原文。长文本保留换行且不撑破容器。页面明确区分虚构示例、AI 解析与基础分段，并提供简历原文入口；当前文件是该档案的证据边界。

### Upload Strip

上传条为白底虚线边框，文字与按钮横向排列；拖入状态改为浅青底和青绿边框，上传中显示独立状态文字，错误同时显示说明文字。移动端按钮自然换行，装饰图标隐藏，操作保持可见。

### Matching Jobs Filters

白色筛选区使用现有 select 控件，标签与选择框分行。可展开的隐私说明默认打开，职业标签是浅青色只读矩形标记，不能当作筛选按钮。搜索按钮实际使用深墨蓝 primary 变体；本页未将其改为青绿。控件沿用全局键盘焦点轮廓。

搜索阶段以文字列出联网搜索、核验与评分，当前阶段用青绿粗体，完成阶段用依据深青。状态区使用 `role="status"` 与 polite 实时通知。准备、搜索中、失败和零结果均显示文字；搜索中结果区标记 `aria-busy`，筛选与搜索锁定。初始空态、失败与零结果共用白底虚线说明面，不填入未经核验的岗位。

搜索不足目标时会继续补搜，并逐步显示通过核验的岗位；状态文字显示已检查网页数与已找到岗位数。补搜期间已有岗位行的标题与分析按钮禁用，完成后开放。列表标题下显示网页检查数、重复结果合并数，达到上限时明确说明，避免将本次上限误解为全网全部岗位。

### Matching Job Row

职位是可点击的文本按钮；悬停转青绿并加下划线，下划线偏移（4px）。右侧显示青绿快速分、分母与深墨蓝分析按钮；标题与分析按钮进入同一分析流程。公司、城市、招聘类型、毕业届次、类别与招聘原页分层呈现。评分依据与被排除链接使用原生 details 展开，核验时间伴随来源显示；警告以浅橙底和深橙文字补充说明。

分析任一岗位时，整个结果区标记 `aria-busy="true"`，所有职位标题与分析按钮以及筛选、搜索均禁用；状态文本点明当前岗位及重新核验、报告生成过程。标题禁用时透明度为（0.55），使用等待光标并取消下划线；普通按钮沿用既有禁用样式。完成或出错后恢复控件，成功状态指向「分析岗位」报告；报错保留原因文字。报告前的白色来源条承接招聘原页、核验信息与快速分上下文。

## Do's and Don'ts

岗位报告“为什么”仅保留一个“公司背景”入口，内容使用连续段落与来源引用；加载、无来源、虚构主体和失败分别说明，失败时提供“重新背调”。岗位解析将核心能力、加分项分组，硬门槛标签保持完整不拆字。“怎么准备”仅展示面试准备：先简历侧经历问题，再职位侧业务/专业问题。每题默认展示考察点、回答结构和要点，原文依据、知识点、追问与易错点使用原生details展开，保持现有纸面、细线与青绿链接风格。

岗位分析页的导入区由44px按钮控制展开与收起，并同步 `aria-expanded` 与面板 `hidden`。点击分析立即进入并聚焦稳定的结果区域，等待卡片标明当前岗位、公司与实际处理步骤；模型结果在同一区域替换，不在返回时再次跳转。失败也在结果区提供恢复入口。展开导入区可查看自动带入的JD，处理期间表单锁定，完成后恢复原有禁用状态。

### Do:

- **Do** 沿用深蓝外壳、冷灰纸面与青绿操作色，并保留档案页的白色平整模块。
- **Do** 在字段附近保留原文依据与行号，清晰展示当前文件和解析来源。
- **Do** 保持移动端单列阅读，让简历切换与模块目录各自横向滚动。
- **Do** 同时用文字和视觉状态说明加载、空模块、失败及禁用。
- **Do** 在匹配岗位横行保留招聘原页、核验时间和可展开的评分依据；移动端将分数与分析按钮放在底部操作行。
- **Do** 分析岗位期间锁定全部同类入口及筛选，用状态文字指出正在处理的岗位，并在完成或失败后恢复操作。

### Don't:

- **Don't** 在档案模块增加通用卡片阴影，或将只读字段伪装成编辑输入框。
- **Don't** 用简历外补充经历填充模块，未体现的能力按未体现呈现。
- **Don't** 因为参考了 OfferLink 的组成而替换 OfferOS 已有配色和品牌字体。
- **Don't** 把简历档案的两栏结构当成其他页面必须遵守的模板。
