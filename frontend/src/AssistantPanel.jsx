import Assistant from './Assistant.jsx'
import AgentTerminal from './AgentTerminal.jsx'
import { Tabs } from './ui.jsx'
import { usePrefs } from './prefs.jsx'

/** The Assistant screen: Fix (the agent that changes code, judged by Paladin) and Ask (questions about the paths). */
export default function AssistantPanel(props) {
  const { prefs, set } = usePrefs()
  const mode = prefs['assistant.mode'] === 'ask' ? 'ask' : 'fix'
  return (
    <div className="assistant-panel">
      <div className="assistant-modes">
        <Tabs label="Assistant mode" value={mode} onChange={(v) => set('assistant.mode', v)}
              tabs={[{ id: 'fix', label: 'Fix (agent)' }, { id: 'ask', label: 'Ask' }]} />
      </div>
      {mode === 'fix' ? <AgentTerminal {...props} /> : <Assistant {...props} />}
    </div>
  )
}
