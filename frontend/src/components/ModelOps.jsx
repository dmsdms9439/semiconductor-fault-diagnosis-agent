import React, { useState } from 'react';
import { Settings, Sliders, Database, RefreshCw } from 'lucide-react';

const ModelOps = () => {
  const [noiseLevel, setNoiseLevel] = useState(1.5);
  const [spikeProb, setSpikeProb] = useState(10);
  const [isGenerating, setIsGenerating] = useState(false);
  const [genStatus, setGenStatus] = useState(null); // 'success' or null

  const handleGenerate = () => {
    setIsGenerating(true);
    setGenStatus(null);
    setTimeout(() => {
      setIsGenerating(false);
      setGenStatus('success');
      setTimeout(() => setGenStatus(null), 3000);
    }, 1500);
  };

  const models = [
    { name: "Standard AE (Baseline)", status: "Deployed", f1: "0.85", type: "baseline" },
    { name: "LSTM AE (Time-series)", status: "Trained", f1: "0.92", type: "ready" },
    { name: "Conv1D AE (Spike Pattern)", status: "Untrained", f1: "-", type: "pending" },
    { name: "GRU Denoising AE (Advanced)", status: "Training...", f1: "-", type: "training" },
  ];

  return (
    <div className="tab-content">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <Settings size={24} color="var(--text-secondary)" />
        <h2>Data Augmentation & Model Ops</h2>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '1.5rem', height: '400px' }}>
        
        {/* 왼쪽: Data Augmentation */}
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginBottom: '1.5rem', fontSize: '1rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Database size={18} /> Augmentation Pipeline
          </h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', flex: 1 }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.9rem' }}>Gaussian Noise Level</span>
                <span style={{ color: 'var(--accent-cyan)', fontWeight: 'bold' }}>{noiseLevel.toFixed(1)}</span>
              </div>
              <input 
                type="range" min="0" max="5" step="0.1" 
                value={noiseLevel} onChange={(e) => setNoiseLevel(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--accent-cyan)' }}
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.9rem' }}>Spike Injection Probability</span>
                <span style={{ color: 'var(--accent-red)', fontWeight: 'bold' }}>{spikeProb}%</span>
              </div>
              <input 
                type="range" min="0" max="50" step="1" 
                value={spikeProb} onChange={(e) => setSpikeProb(parseInt(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--accent-red)' }}
              />
            </div>

            <div style={{ marginTop: 'auto' }}>
              <button 
                onClick={handleGenerate}
                disabled={isGenerating}
                className="start-btn" 
                style={{ width: '100%', background: isGenerating ? 'rgba(255,255,255,0.1)' : 'var(--bg-dark)', border: '1px solid var(--border-color)' }}
              >
                {isGenerating ? <><RefreshCw className="animate-spin" size={18} /> Generating...</> : <><Sliders size={18} /> Generate Augmented Data</>}
              </button>
              {genStatus === 'success' && (
                <p style={{ color: 'var(--accent-green)', fontSize: '0.8rem', textAlign: 'center', marginTop: '0.5rem' }}>✅ Data generation complete!</p>
              )}
            </div>
          </div>
        </div>

        {/* 오른쪽: Model Registry */}
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginBottom: '1.5rem', fontSize: '1rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Settings size={18} /> Model Registry
          </h3>
          
          <table className="logs-table" style={{ flex: 1 }}>
            <thead>
              <tr>
                <th>Model Architecture</th>
                <th>Status</th>
                <th>Accuracy (F1)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {models.map((model, idx) => (
                <tr key={idx}>
                  <td style={{ fontWeight: model.type === 'baseline' ? 'bold' : 'normal', color: model.type === 'baseline' ? 'var(--accent-cyan)' : 'inherit' }}>
                    {model.name}
                  </td>
                  <td>
                    <span className={`badge ${model.type === 'baseline' ? 'normal' : model.type === 'training' ? 'anomaly' : ''}`} style={model.type === 'pending' ? { background: 'rgba(255,255,255,0.1)', color: 'var(--text-secondary)' } : {}}>
                      {model.status}
                    </span>
                  </td>
                  <td>{model.f1}</td>
                  <td>
                    {model.type !== 'training' && (
                      <button style={{ background: 'transparent', border: '1px solid var(--accent-cyan)', color: 'var(--accent-cyan)', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.8rem' }}>
                        Retrain
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
      </div>
      <style>{`
        .animate-spin { animation: spin 1s linear infinite; }
      `}</style>
    </div>
  );
};

export default ModelOps;
