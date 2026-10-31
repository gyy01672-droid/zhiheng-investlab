"""Single native window with a bundled Chromium engine; no external browser."""
import sys, socket, threading, json
from pathlib import Path

def run(app,models,llm,store,alerts,updates,state):
    from PySide6.QtCore import QUrl, QTimer, Qt
    from PySide6.QtGui import QIcon
    from .config import ROOT
    from PySide6.QtWidgets import QApplication,QMainWindow,QMessageBox
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Zhiheng.InvestLab.Desktop')
    qt=QApplication(sys.argv);qt.setApplicationName('知衡 InvestLab')
    qt.setWindowIcon(QIcon(str(ROOT/'web/investlab.ico')))
    # Each instance owns its API and model process; never attach to an unknown service.
    store.init();server=app.LocalServer(('127.0.0.1',0),app.Handler)
    app.PORT=server.server_address[1]
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));llm.PORT=probe.getsockname()[1]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    smoke='--ui-smoke-test' in sys.argv
    if not smoke:
        app.background(alerts.scheduler);app.background(updates.scheduler)
    class Window(QMainWindow):
        def closeEvent(self,event):
            if not smoke and (models.STATUS['running'] or updates.STATUS['running']):
                QMessageBox.information(self,'任务正在运行','请等待当前更新或训练完成后退出。');event.ignore();return
            event.accept()
    window=Window();window.setWindowTitle('知衡 · 本地投资研究台');window.resize(1280,860)
    views=[];details=[]
    profile=QWebEngineProfile('InvestLab',window)
    profile.setPersistentStoragePath(str(state/'browser'))
    profile.setCachePath(str(state/'browser-cache'))
    class View(QWebEngineView):
        def createWindow(self,kind):
            detail=QMainWindow(window,Qt.Window)
            detail.setAttribute(Qt.WA_DeleteOnClose)
            detail.resize(1100,780);detail.setWindowTitle('资料详情 · 知衡')
            child=new_view(detail);detail.setCentralWidget(child)
            child.titleChanged.connect(lambda title: detail.setWindowTitle(title+' · 知衡'))
            details.append(detail);detail.show();return child
    def new_view(parent):
        view=View(parent);view.setPage(QWebEnginePage(profile,view));views.append(view)
        return view
    view=new_view(window);window.setCentralWidget(view)
    window.statusBar().showMessage('正在加载软件界面…')
    def loaded(ok):
        window.statusBar().showMessage('本机运行 · 关闭窗口退出软件' if ok else '界面加载失败，请关闭后重试')
        if smoke:
            (state/'ui-smoke.json').write_text(json.dumps({'loaded':ok,'title':view.title(),'api_port':app.PORT,'engine':'Qt WebEngine','custom_icon':not qt.windowIcon().isNull(),'central_widget':window.centralWidget().metaObject().className()},ensure_ascii=False),encoding='utf-8')
            QTimer.singleShot(2500,qt.quit)
    view.loadFinished.connect(loaded)
    view.load(QUrl(f'http://127.0.0.1:{app.PORT}/'));window.show()
    if smoke:QTimer.singleShot(45000,qt.quit)
    try:qt.exec()
    finally:
        server.shutdown();server.server_close();llm.stop()
        # Pages must be destroyed before their profile.
        for current in views:
            try:current.setPage(QWebEnginePage(current))
            except RuntimeError:pass
