# JLCEDA2KICAD

JLCEDA2KICAD 是一个非官方、Windows 优先的 KiCad 纯 IPC 插件。它一次处理一个
LCSC C 编号，使用 PySide6 异步调用 `easyeda2kicad`，先在唯一临时目录预览，
再在影子工程正式转换和校验，最后以备份、原子替换和回滚机制导入当前工程本地库或
KiCad 全局个人库。

0.1.0 面向 KiCad 9.0.1+ 和 KiCad 10。首版 PCM 元数据仅声明 Windows 支持；
核心逻辑同时在 Windows 与 Ubuntu CI 测试。

## 主要功能

- 通过官方 KiCad IPC API 识别当前 PCB 工程，失败时可手动选择工程文件、PCB 或目录。
- 严格校验单个 C 编号，使用参数列表和 `sys.executable` 启动转换，不经过 shell。
- 实时显示并脱敏命令输出，支持 120 秒默认超时和“先 terminate、后 kill”的取消。
- 预览符号 SVG、KiCad 封装焊盘及常用图元、WRL 软件投影模型。
- 在影子工程中分别执行符号、封装和 3D 正式转换。
- 事务式写入 `libs/lcsc_project.kicad_sym`、`.pretty` 和 `.3dshapes`，并幂等注册
  工程级 `LCSC_Project` 库表。
- 可分别选择已有或待创建的 KiCad 全局符号库和封装库，并分别编辑元件名称。
- 每次提交生成带 SHA-256 清单的工程内备份；失败时恢复旧文件并删除本次新增文件。
- 冲突时可取消、仅跳过已有项，或只覆盖当前元件节点及同名文件。
- 保存最近工程、窗口状态、导入选项、10 条历史、轮转日志和最近 5 次备份。

0.1.0 不包含批量导入、BOM、库存/价格、登录、服务器、数据库、遥测或团队功能。

## 环境要求

- Windows 10/11
- KiCad 9.0.1 或更高版本（含 KiCad 10）
- KiCad 自带 Python 3.11
- `easyeda2kicad==1.0.1`
- `kicad-python==0.7.1`
- `PySide6==6.11.1`

插件使用 `runtime: ipc`，不使用旧版 `pcbnew` SWIG API。

## 开发安装

只复制本插件到 KiCad 9/10 用户 IPC 插件目录：

```powershell
./scripts/install_dev.ps1
```

重启 PCB 编辑器；若插件没有自动加载，请选择“工具 → 外部插件 → 刷新插件”。KiCad
会建立插件专用 Python 环境并按 `requirements.txt` 安装固定依赖，不要使用 `--user`
把依赖装入 KiCad 的基础 Python。工具栏中的绿色 JLC 按钮就是
**JLCEDA2KICAD Importer**。卸载只删除本插件：

```powershell
./scripts/uninstall_dev.ps1
```

只有明确要同时清理本应用设置、缓存、历史和日志时，才添加 `-PurgeAppData`。

## 使用流程

1. 在 PCB 编辑器打开一个隔离测试工程并启动插件。
2. 确认自动识别的工程，或手动选择 `.kicad_pro`、`.kicad_pcb` 或工程目录。
3. 输入一个 C 编号（例如 `C2040`），点击“查询并预览”。
4. 检查符号、封装、3D 和日志标签页；部分预览失败不会清除其他成功产物。
5. 点击“导入当前工程”，若有冲突则选择取消、跳过或覆盖当前元件。
6. 检查报告和工程 `libs`；备份位于工程的 `.jlceda2kicad_backup`。

## 全局个人库

工程模式仍写入所选工程内的 `libs/lcsc_project.kicad_sym`、
`libs/lcsc_project.pretty` 和 `libs/lcsc_project.3dshapes`。若要改为导入当前
KiCad 用户注册的库：

1. 查询并预览一个 LCSC 元件。
2. 将导入目标选择为“KiCad 全局个人库”。
3. 分别选择符号库和封装库。两个选择器都可以使用已有可写库，也可以新建“待创建”
   库；后者只会在导入事务提交时注册。
4. 分别编辑符号名称和封装名称，二者互不绑定。
5. 核对界面显示的同级 `.3dshapes` 目录，以及最终
   `<封装库昵称>:<封装名称>` 关联；同时导入符号和封装时才会应用该关联。
6. 执行导入，并在结果对话框中检查准确的符号、封装、模型和备份路径。仅当新注册的
   库没有立即显示时，才重启对应的 KiCad 符号编辑器或封装编辑器；导入器刷新后，
   编辑器仍可能保留库表缓存。

全局导入备份位于应用本地数据目录的 `backups/global/<时间戳-UUID>`（Windows
通常为 `%LOCALAPPDATA%\HKRPT\JLCEDA2KICAD\backups\global`）。清单记录每个
绝对目标路径、原始大小和 SHA-256。当前机器所选全局库中的封装会获得指向上述同级
`.3dshapes` 目录的、经归一化的 STEP/WRL 绝对路径；把库移到其他机器前必须复核
这些引用。自动测试只使用临时替身库，绝不会写入真实 `Harulib` 库。

请先在隔离工程验证。外部元件数据和转换结果必须人工核对引脚、焊盘、尺寸、方向及
3D 模型后才能用于制造。

## 开发与打包

```powershell
python -m ruff check .
python -m mypy src
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest --cov=jlceda2kicad
python scripts/build_package.py
python -m kipy.packaging validate dist/JLCEDA2KICAD-0.1.0.zip
```

普通测试禁止网络。只有设置 `RUN_LIVE_LCSC_TESTS=1` 时才执行 C2040 在线转换。

更多信息见 [开发文档](docs/DEVELOPMENT.md)、
[人工测试清单](docs/MANUAL_TEST_CHECKLIST.md) 和
[第三方声明](THIRD_PARTY_NOTICES.md)。

## 许可证与声明

本项目代码采用 MIT。依赖项保留各自许可证，其中 `easyeda2kicad` 为 AGPL-3.0。
本项目与 JLCPCB、LCSC、EasyEDA 或 KiCad 均无隶属或官方合作关系。
