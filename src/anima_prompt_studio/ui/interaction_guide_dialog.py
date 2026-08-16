from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)


class InteractionGuideDialog(QDialog):
    """In-app writing guide for body actions and scene interactions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("复杂动作与场景互动写法")
        self.resize(860, 650)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "复杂动作请写清楚“人物—动作—对象—接触点—前后状态—构图”。"
            "工具会尽量保留明确关系；精确姿势和场景互动仍可能需要对应 LoRA 或姿势控制。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "background:#eef4ff;color:#234a83;border:1px solid #c9daf8;"
            "border-radius:5px;padding:9px;"
        )
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._page(self._principles_html()), "写法原则")
        self.tabs.addTab(self._page(self._body_html()), "手脚与身体动作")
        self.tabs.addTab(self._page(self._scene_html()), "场景互动")
        self.tabs.addTab(self._page(self._limits_html()), "模型边界")
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _page(html: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(html)
        layout.addWidget(browser)
        return page

    @staticmethod
    def _principles_html() -> str:
        return """
        <h2>推荐句式</h2>
        <p><b>人物 + 核心动作 + 交互对象 + 精确接触 + 对象状态 + 遮挡 + 构图</b></p>
        <p>示例：成年女性坐在高脚凳边缘，右脚踝搭在左膝上，左脚完整踩地，
        右手扶住抬起的膝盖，使用三分之四全身视角。</p>
        <h3>写作要点</h3>
        <ul>
          <li>使用“左手、右手、左脚、右脚”，不要只写“手脚摆好”。</li>
          <li>写清接触对象，例如“右手握住门把手”，不要只写“伸手开门”。</li>
          <li>写清动作阶段，例如“正要挥拳”“撞击瞬间”“已经穿到一半”。</li>
          <li>写清物体原始状态，例如“已有洞口”或“完整墙面”。</li>
          <li>写清前后遮挡，例如“上身在墙前、下身在墙后”。</li>
          <li>一个画面尽量只保留一个主要动作瞬间。</li>
        </ul>
        <h3>不推荐</h3>
        <p>“女孩很有力量地和墙互动，动作富有张力。”这类抽象描述没有可执行的接触点和空间关系。</p>
        """

    @staticmethod
    def _body_html() -> str:
        return """
        <h2>手部动作</h2>
        <p><b>推荐：</b>右手五指张开，手掌平贴窗框；左手自然垂在身体侧面。</p>
        <p><b>推荐：</b>双手握住栏杆，左右手分开，十根手指包住同一根横杆。</p>
        <p><b>避免：</b>双手扶着、手放在旁边、做一个复杂手势。</p>
        <h2>身体行为</h2>
        <p><b>推荐：</b>人物侧躺在床上，右侧身体贴床，双膝轻微弯曲，左手放在枕头前。</p>
        <p><b>推荐：</b>人物弯腰向前，肩膀低于臀部，右手伸向地上的书。</p>
        <h2>腿部动作</h2>
        <p><b>推荐：</b>右脚踝搭在左膝上，左脚完整踩地，右脚尖朝下，三分之四全身视角。</p>
        <p>复杂腿部关系应同时写明左右侧、支撑脚、抬起脚和是否需要完整脚部入镜。</p>
        """

    @staticmethod
    def _scene_html() -> str:
        return """
        <h2>描述场景互动</h2>
        <p>先写动作发生前的物体状态，再写接触点和动作瞬间。例如“右手握住关闭的门的把手，
        身体后倾并向自己方向拉门”，比“正在开门”更明确。</p>
        <h3>常见对象</h3>
        <ul>
          <li>门：原本关闭/已经打开；推门/拉门；手掌或门把手接触。</li>
          <li>窗：身体在室内或室外；手扶窗框；哪些身体部位越过窗框。</li>
          <li>玻璃：完整透明/正在碎裂/已经破碎；撞击点和碎片方向。</li>
          <li>家具：人物坐、靠、扶、踩的位置，以及家具承担身体重量的位置。</li>
        </ul>
        <h3>不要混合相邻意图</h3>
        <p>“穿过已有洞口”“正在砸墙”“破墙而出”是不同动作。请只选择一个动作瞬间，
        不要为了强化效果把三种描述同时堆进提示词。</p>
        """

    @staticmethod
    def _limits_html() -> str:
        return """
        <h2>如何判断是工具问题还是模型问题</h2>
        <ol>
          <li>先查看最终英文是否保留左右侧、接触点、对象原始状态和遮挡关系。</li>
          <li>查看正向标签是否出现与动作无关的词，例如把“方形构图”识别成方形物体。</li>
          <li>用相同参数更换几个种子，判断问题是随机波动还是稳定失败。</li>
          <li>提示词正确但多个种子仍失败时，更可能需要专用 LoRA、姿势控制或局部修复。</li>
        </ol>
        <h2>纯提示词不稳定的情况</h2>
        <p>精确手指、多人肢体接触、身体穿过狭窄空间、复杂遮挡、连续动作和物体形变通常难以只靠提示词稳定控制。
        这类需求优先寻找与当前 ANIMA 版本兼容的姿势 LoRA；没有合适 LoRA 时，再考虑姿势控制、深度控制或局部修复。
        工具只负责减少语义丢失和冲突，不承诺基础模型一定能完成复杂空间关系。</p>
        """
