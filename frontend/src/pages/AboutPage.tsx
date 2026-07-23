import { IslandCard } from "../components/island/IslandCard";

export function AboutPage() {
  return <div className="page about-page"><header><p className="eyebrow">About</p><h1>项目与第三方组件说明</h1></header><IslandCard title="animal-island-ui"><p>部分界面组件基于 animal-island-ui 1.3.0，依照 CC BY-NC 4.0 用于当前私人、非商业研究范围，并通过 The Leopard Project 的封装层进行了布局、业务样式及交互适配。</p><ul><li>作者：guokaigdg</li><li><a href="https://github.com/guokaigdg/animal-island-ui" target="_blank" rel="noreferrer">查看原项目</a></li><li><a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noreferrer">查看 CC BY-NC 4.0 许可证</a></li></ul><p className="muted">本项目不是组件作者或相关游戏权利方的官方产品，也不暗示其授权、赞助或背书。</p></IslandCard></div>;
}
