# 第三方组件与模型

本仓库为公开的课程项目。公开可见不意味着所有文件使用同一种许可证；项目原创代码暂未另行指定开放许可。第三方组件保留其各自许可，完整文本见 licenses 目录及运行库随附文本。

- Qwen3-4B-Instruct-2507：Qwen，Apache-2.0。量化文件来自 unsloth/Qwen3-4B-Instruct-2507-GGUF；上游模型：https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 。版本及 SHA-256 见 models/download_manifest.json。
- llama.cpp b11951：ggml-org，MIT；https://github.com/ggml-org/llama.cpp 。分发目录包含上游 CPU DLL 和 LLVM OpenMP 许可。
- LightGBM：Microsoft，MIT。项目的数值判断权重在本地训练，模型清单记录来源、特征及验证结果。
- NumPy、SciPy、scikit-learn、joblib、threadpoolctl、narwhals：许可证随包保存于 licenses 对应目录；这些组件及其包含的数值运行库可能各有附加许可。
- Python 运行时使用 PSF 许可及附属许可；PyInstaller 引导程序遵循其许可证与分发例外。Tk/Tcl 许可随运行时及 licenses 保存。

使用腾讯证券公开行情、东方财富公开新闻和公告、新浪公开数据，不代表获得它们的背书或永久服务承诺。公开仓库不包含完整行情训练快照、个人账户记录、私有凭据、教师原始 PDF 或原始 Word 模板。

## 内嵌桌面界面
PySide6 / Qt 6.12（LGPL/GPL/商业多许可，使用适用LGPL发行组件）及 Qt WebEngine / Chromium，许可证随 licenses 目录及运行库提供。Qt组件动态链接，可替换兼容版本；本项目不限制为调试这些组件而进行的逆向工程。官方源码及许可：https://code.qt.io/ ，https://doc.qt.io/qt-6/licenses-used-in-qt.html 。
