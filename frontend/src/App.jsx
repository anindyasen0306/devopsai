import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [backendStatus, setBackendStatus] = useState('Checking backend...')
  const [healthData, setHealthData] = useState(null)

  useEffect(() => {
    fetch('http://127.0.0.1:8000/api/health')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Backend returned an error status')
        }
        return response.json()
      })
      .then((data) => {
        setHealthData(data)
        setBackendStatus('Backend Status: Connected')
      })
      .catch(() => {
        setBackendStatus('Backend Status: Disconnected')
      })
  }, [])

  return (
    <div className="app-container">
      <h1>DevOpsAI</h1>
      <p className="subtitle">Autonomous AI Engineering Agent</p>

      <div className="status-box">
        <p>{backendStatus}</p>
        {healthData && (
          <pre className="health-data">
            {JSON.stringify(healthData, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

export default App
