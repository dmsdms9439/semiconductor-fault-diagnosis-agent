import React, { memo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush } from 'recharts';
import { Activity, AlertTriangle } from 'lucide-react';

const CustomDot = (props) => {
  const { cx, cy, payload, onAnomalyClick } = props;
  
  if (payload.is_anomaly) {
    return (
      <circle 
        cx={cx} 
        cy={cy} 
        r={6} 
        fill="var(--accent-red)" 
        stroke="white" 
        strokeWidth={2}
        style={{ cursor: 'pointer' }}
        onClick={() => onAnomalyClick && onAnomalyClick(payload.time)}
      >
        <title>클릭하여 이상 원인 분석 보기</title>
      </circle>
    );
  }
  return null;
};

const LiveDashboard = ({ latestMetrics, metricsHistory, isRunning, selectedModel, onAnomalyClick, equipmentId, topCandidates }) => {
  const { mse, status, confidence, is_anomaly } = latestMetrics;

  return (
    <div className="tab-content">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        <div className="glass-panel">
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>설비 ID</p>
          <h3 style={{ fontSize: '1.5rem', marginTop: '0.5rem', color: 'var(--accent-cyan)' }}>{equipmentId || 'EQ-01'} (Etch)</h3>
        </div>
        <div className="glass-panel">
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>현재 이상 지수 (MSE)</p>
          <h3 style={{ fontSize: '1.5rem', marginTop: '0.5rem', color: is_anomaly ? 'var(--accent-red)' : 'white' }}>
            {mse.toFixed(4)}
          </h3>
        </div>
        <div className="glass-panel">
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>판정 신뢰도</p>
          <h3 style={{ fontSize: '1.5rem', marginTop: '0.5rem' }}>{(confidence * 100).toFixed(1)}%</h3>
        </div>
        <div className={`glass-panel ${is_anomaly ? 'anomaly-pulse' : ''}`} style={{ border: is_anomaly ? '1px solid var(--accent-red)' : '' }}>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>현재 상태</p>
          <h3 style={{ fontSize: '1.5rem', marginTop: '0.5rem', color: is_anomaly ? 'var(--accent-red)' : 'var(--accent-green)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {is_anomaly ? <AlertTriangle size={24} /> : <Activity size={24} />}
            {status}
          </h3>
        </div>

        {/* 의심되는 고장 원인 TOP 3 (재현율 보정) */}
        {is_anomaly && topCandidates && topCandidates.length > 0 && (
          <div className="glass-panel" style={{ gridColumn: 'span 4', border: '1px solid rgba(255, 71, 87, 0.4)', background: 'rgba(255, 71, 87, 0.05)', animation: 'fadeIn 0.5s ease' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <p style={{ color: 'var(--accent-red)', fontSize: '0.9rem', fontWeight: 'bold', whiteSpace: 'nowrap' }}>의심되는 고장 원인 TOP 3 (재현율 보정)</p>
              <div style={{ height: '1px', flex: 1, background: 'rgba(255, 71, 87, 0.2)' }}></div>
              <div style={{ display: 'flex', gap: '2rem' }}>
                {topCandidates.map((c, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.3rem 0.8rem', borderRadius: '4px', background: 'rgba(0,0,0,0.2)' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{i+1}위:</span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 'bold' }}>{c.label}</span>
                    <span style={{ color: 'var(--accent-cyan)', fontSize: '0.85rem' }}>{(c.confidence * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="glass-panel" style={{ height: '350px' }}>
        <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)' }}>
          실시간 이상 지수 (MSE) 추이
        </h3>
        <div style={{ height: 'calc(100% - 30px)', width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={metricsHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="time" stroke="#888" />
              <YAxis domain={['auto', 'auto']} stroke="#888" />
              <Tooltip contentStyle={{ backgroundColor: 'rgba(0,0,0,0.8)', border: '1px solid #333' }} />
              <Line 
                type="monotone" 
                dataKey="mse" 
                stroke="var(--accent-blue)" 
                strokeWidth={2}
                dot={<CustomDot onAnomalyClick={onAnomalyClick} />}
                activeDot={{ r: 8 }}
                isAnimationActive={false}
              />
              <Brush dataKey="time" height={30} stroke="var(--border-color)" fill="var(--bg-card)" tickFormatter={() => ''} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      
      {/* Event Logs Placeholder */}
      <div className="glass-panel">
        <h3 style={{ marginBottom: '1rem', fontSize: '1rem' }}>시스템 이벤트 로그</h3>
        <table className="logs-table">
          <thead>
            <tr>
              <th>시간</th>
              <th>이벤트 내용</th>
              <th>적용 모델</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{new Date().toLocaleTimeString()}</td>
              <td style={{ color: is_anomaly && isRunning ? 'var(--accent-red)' : 'inherit' }}>
                {isRunning ? (is_anomaly ? '이상 징후 발생!' : '정상 작동 중') : '대기 상태'}
              </td>
              <td>{selectedModel}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default memo(LiveDashboard);
