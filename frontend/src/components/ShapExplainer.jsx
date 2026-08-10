import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { BrainCircuit, Loader2, AlertCircle } from 'lucide-react';

const ShapExplainer = ({ shapHistory, shapData, explanation, topCandidates, isRunning, onSelectAnomaly }) => {
  const isAnalyzing = isRunning && (!shapData || shapData.length === 0);
  const anomalyTimes = Object.keys(shapHistory || {}).sort((a, b) => b.localeCompare(a)); // 최신순 정렬

  return (
    <div className="tab-content" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <BrainCircuit size={24} color="var(--accent-cyan)" />
        <h2>Root Cause Analysis (SHAP + LLM)</h2>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '250px 350px 1fr', gap: '1.5rem', height: '500px' }}>
        {/* 왼쪽: 이상치 목록 사이드바 */}
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', padding: '1rem' }}>
          <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)' }}>
            이상치 발생 목록 ({anomalyTimes.length})
          </h3>
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {anomalyTimes.length === 0 ? (
              <div style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '2rem', fontSize: '0.9rem' }}>
                발생한 이상치가 없습니다.
              </div>
            ) : (
              anomalyTimes.map((time) => {
                const isActive = shapData && shapHistory[time]?.data === shapData;
                return (
                  <div 
                    key={time}
                    onClick={() => onSelectAnomaly(time)}
                    style={{
                      padding: '0.8rem',
                      background: isActive ? 'rgba(0, 169, 224, 0.15)' : 'rgba(0,0,0,0.2)',
                      border: isActive ? '1px solid var(--accent-cyan)' : '1px solid transparent',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      transition: 'all 0.2s'
                    }}
                  >
                    <AlertCircle size={16} color={isActive ? "var(--accent-cyan)" : "var(--accent-red)"} />
                    <span style={{ fontWeight: isActive ? 'bold' : 'normal', color: isActive ? 'white' : 'var(--text-secondary)' }}>
                      {time} 발생
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* 중앙: SHAP 바 차트 */}
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)' }}>
            Feature Contribution (Top 8)
          </h3>
          <div style={{ flex: 1, position: 'relative' }}>
            {isAnalyzing ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>
                <Loader2 size={32} className="animate-spin" style={{ animation: 'spin 2s linear infinite', marginBottom: '1rem' }} />
                <p>Waiting for anomaly detection...</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={shapData} layout="vertical" margin={{ top: 0, right: 30, left: 40, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis dataKey="name" type="category" stroke="rgba(255,255,255,0.5)" tick={{fill: 'var(--text-secondary)', fontSize: 12}} />
                  <Tooltip 
                    cursor={{fill: 'rgba(255,255,255,0.05)'}}
                    contentStyle={{ backgroundColor: 'rgba(10,10,15,0.9)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {shapData && shapData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={index === 0 ? 'var(--accent-red)' : index === 1 ? 'var(--accent-cyan)' : 'rgba(0, 198, 255, 0.3)'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* 오른쪽: LLM 에이전트 리포트 */}
        <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)' }}>
            AI Diagnostic Report
          </h3>
          <div style={{ 
            flex: 1, 
            background: 'rgba(0,0,0,0.3)', 
            borderRadius: '8px', 
            padding: '1.5rem',
            border: '1px solid var(--border-color)',
            overflowY: 'auto',
            fontFamily: 'inherit',
            fontSize: '1rem',
            lineHeight: '1.6',
            color: 'var(--text-primary)',
            whiteSpace: 'normal'
          }}>
            {!explanation && !isAnalyzing && <div style={{color: 'var(--text-secondary)'}}>목록에서 이상치를 선택해주세요.</div>}
            {isAnalyzing && !explanation && <div style={{color: 'var(--text-secondary)'}}>Waiting for anomaly detection...</div>}
            
            {/* AI 판정 후보군 TOP 3 */}
            {explanation && topCandidates && topCandidates.length > 0 && (
              <div style={{ marginBottom: '1.5rem', padding: '1rem', background: 'rgba(255,255,255,0.05)', borderRadius: '8px', borderLeft: '4px solid var(--accent-cyan)' }}>
                <p style={{ fontSize: '0.85rem', color: 'var(--accent-cyan)', fontWeight: 'bold', marginBottom: '0.6rem', letterSpacing: '0.5px' }}>🎯 AI 판정 후보군 (TOP 3)</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                  {topCandidates.map((c, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                      <span style={{ color: 'white', fontWeight: i === 0 ? 'bold' : 'normal' }}>{i+1}. {c.label}</span>
                      <span style={{ color: 'var(--text-secondary)' }}>{(c.confidence * 100).toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {explanation && explanation.split('\n').map((line, i) => {
              if (line.trim() === '') return <div key={i} style={{ height: '0.8rem' }} />;
              const parts = line.split(/(\*\*.*?\*\*)/g);
              return (
                <div key={i} style={{ marginBottom: '0.4rem' }}>
                  {parts.map((part, j) => {
                    if (part.startsWith('**') && part.endsWith('**')) {
                      return <strong key={j} style={{ color: 'var(--accent-cyan)' }}>{part.slice(2, -2)}</strong>;
                    }
                    return <span key={j}>{part}</span>;
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <style>{`
        @keyframes spin { 100% { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
};

export default ShapExplainer;
