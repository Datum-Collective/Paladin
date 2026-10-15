import { Component } from 'react'

/** A failure while drawing the graph must not take the whole workspace down with it. */
export default class GraphBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  componentDidUpdate(prev) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="empty" role="alert">
        <h2>The graph could not be shown</h2>
        <p className="muted">{String(this.state.error.message || this.state.error)}</p>
        <div className="actions center"><button onClick={() => this.setState({ error: null })}>Try Again</button></div>
      </div>
    )
  }
}
