import React, { memo } from 'react';
import { Activity, AlertTriangle, CheckCircle, AlertCircle } from 'lucide-react';

const FleetOverview = ({ fleetStatus, onSelectEquipment }) => {
  // equipment IDs from 1 to 10
  const equipments = Array.from({ length: 10 }, (_, i) => `EQ-${String(i + 1).padStart(2, '0')}`);

  return (
    <div className="tab-content" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '1.5rem' }}>
        <h2 style={{ color: 'var(--text-primary)', margin: 0 }}>전체 설비 현황 (Fleet Overview)</h2>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Real-time monitoring of 10 active etch chambers
        </div>
      </div>

      {/* Fleet Summary Statistics */}
      <div className="glass-panel" style={{ 
        marginBottom: '2rem', 
        padding: '1.5rem 2rem', 
        display: 'flex', 
        alignItems: 'center', 
        gap: '3rem',
        background: 'linear-gradient(90deg, rgba(0, 169, 224, 0.05) 0%, rgba(0, 200, 150, 0.05) 100%)',
        border: '1px solid rgba(0, 169, 224, 0.2)'
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.8rem' }}>
            <span style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>공정 가동 효율 (Fleet Health)</span>
            <span style={{ fontSize: '1.1rem', fontWeight: 'bold', color: 'var(--accent-cyan)' }}>
              {((equipments.filter(id => !fleetStatus[id]?.is_anomaly).length / equipments.length) * 100).toFixed(0)}%
            </span>
          </div>
          <div style={{ height: '8px', background: 'rgba(255,255,255,0.1)', borderRadius: '4px', overflow: 'hidden' }}>
            <div style={{ 
              height: '100%', 
              width: `${(equipments.filter(id => !fleetStatus[id]?.is_anomaly).length / equipments.length) * 100}%`,
              background: 'var(--accent-cyan)',
              boxShadow: '0 0 10px var(--accent-cyan)',
              transition: 'width 0.5s ease-out'
            }} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '2rem' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-green)', marginBottom: '0.3rem' }}>
              <CheckCircle size={18} />
              <span style={{ fontSize: '0.85rem', fontWeight: 'bold' }}>정상 가동</span>
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 'bold' }}>
              {equipments.filter(id => !fleetStatus[id]?.is_anomaly).length}
            </div>
          </div>

          <div style={{ width: '1px', height: '40px', background: 'var(--border-color)' }} />

          <div style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-red)', marginBottom: '0.3rem' }}>
              <AlertCircle size={18} />
              <span style={{ fontSize: '0.85rem', fontWeight: 'bold' }}>이상/정지</span>
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: equipments.filter(id => fleetStatus[id]?.is_anomaly).length > 0 ? 'var(--accent-red)' : 'var(--text-primary)' }}>
              {equipments.filter(id => fleetStatus[id]?.is_anomaly).length}
            </div>
          </div>
        </div>
      </div>
      
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', 
        gap: '1.5rem' 
      }}>
        {equipments.map((eqId) => {
          const statusData = fleetStatus[eqId] || { mse: 0, status: '대기 중', is_anomaly: false };
          const isAnomaly = statusData.is_anomaly;

          return (
            <div 
              key={eqId}
              onClick={() => onSelectEquipment(eqId)}
              className={`glass-panel ${isAnomaly ? 'anomaly-pulse' : ''}`}
              style={{ 
                cursor: 'pointer',
                border: isAnomaly ? '2px solid var(--accent-red)' : '1px solid var(--border-color)',
                transition: 'all 0.2s',
                display: 'flex',
                flexDirection: 'column',
                gap: '1rem'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ fontSize: '1.4rem', color: isAnomaly ? 'var(--accent-red)' : 'var(--text-primary)' }}>
                  {eqId}
                </h3>
                {isAnomaly ? <AlertTriangle size={24} color="var(--accent-red)" /> : <Activity size={24} color="var(--accent-cyan)" />}
              </div>
              
              <div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '0.2rem' }}>현재 상태</p>
                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: isAnomaly ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                  {statusData.status}
                </div>
              </div>
              
              <div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '0.2rem' }}>이상 지수 (MSE)</p>
                <div style={{ fontSize: '1.2rem', color: isAnomaly ? 'var(--accent-red)' : 'var(--text-primary)' }}>
                  {statusData.mse.toFixed(4)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default memo(FleetOverview);
