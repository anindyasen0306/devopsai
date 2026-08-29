import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [backendStatus, setBackendStatus] = useState('Checking backend...')
  const [healthData, setHealthData] = useState(null)

  const [repositories, setRepositories] = useState([])
  const [reposLoading, setReposLoading] = useState(true)
  const [reposError, setReposError] = useState(null)
  const [selectedRepo, setSelectedRepo] = useState('')

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

  useEffect(() => {
    fetch('http://127.0.0.1:8000/api/github/repos')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to fetch repositories')
        }
        return response.json()
      })
      .then((data) => {
        setRepositories(data)
        setReposLoading(false)
      })
      .catch(() => {
        setReposError('Could not load repositories.')
        setReposLoading(false)
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

      <div className="status-box">
        <h2>Select Repository</h2>

        {reposLoading && <p>Loading repositories...</p>}
        {reposError && <p>{reposError}</p>}

        {!reposLoading && !reposError && (
          <select
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
          >
            <option value="">-- Choose a repository --</option>
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.full_name}>
                {repo.full_name}
              </option>
            ))}
          </select>
        )}

        {selectedRepo && (
          <p>Selected: {selectedRepo}</p>
        )}
      </div>
    </div>
  )
}

export default App