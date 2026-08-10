import React from 'react';
import { TrendingUp, Target, Database, Zap, X, Award, BarChart3, ShieldCheck } from 'lucide-react';

const AccomplishmentsDashboard = ({ onClose }) => {
  const stats = [
    { 
      label: 'Top-3 Recall', 
      value: '86%', 
      sub: 'Multi-Class Performance', 
      icon: Target, 
      color: 'var(--accent-cyan)' 
    },
    { 
      label: 'Unknown Fault Detection', 
      value: '87.05%', 
      sub: 'Anomaly Detection Rate', 
      icon: ShieldCheck, 
      color: 'var(--accent-green)' 
    },
    { 
      label: 'Augmented Data', 
      value: '15,000+', 
      sub: 'Synthetic Samples', 
      icon: Database, 
      color: 'var(--accent-cyan)' 
    },
    { 
      label: 'Inference Speed', 
      value: '<15ms', 
      sub: 'Real-time Processing', 
      icon: Zap, 
      color: 'var(--accent-red)' 
    },
  ];

  const highlights = [
    "통합 데이터 파이프라인 (OES + RFM + Machine Log) 구축 완료",
    "Autoencoder 기반 미지 결함 탐지 알고리즘 최적화",
    "LightGBM 앙상블을 통한 다중 결함 분류 정밀도 향상",
    "SHAP 분석을 통한 결함 원인 설명력(XAI) 확보"
  ];

  return (
    <div className="dashboard-overlay">
      <div className="accomplishments-container glass-panel">
        <button className="close-btn" onClick={onClose}>
          <X size={24} />
        </button>

        <div className="dashboard-header">
          <Award size={40} color="var(--accent-cyan)" />
          <div>
            <h2>Model Development Accomplishments</h2>
            <p>프로젝트 성과 및 모델 성능 지표 요약</p>
          </div>
        </div>

        <div className="stats-grid">
          {stats.map((stat, idx) => {
            const Icon = stat.icon;
            return (
              <div key={idx} className="stat-card" style={{ borderLeft: `4px solid ${stat.color}` }}>
                <div className="stat-icon-bg" style={{ background: `${stat.color}15` }}>
                  <Icon size={24} color={stat.color} />
                </div>
                <div className="stat-info">
                  <span className="stat-label">{stat.label}</span>
                  <span className="stat-value">{stat.value}</span>
                  <span className="stat-sub">{stat.sub}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="highlights-section">
          <h3><TrendingUp size={20} /> Key Project Highlights</h3>
          <ul className="highlights-list">
            {highlights.map((text, i) => (
              <li key={i}>
                <div className="list-dot" />
                {text}
              </li>
            ))}
          </ul>
        </div>

        <div className="performance-footer">
          <div className="footer-item">
            <BarChart3 size={18} />
            <span>최종 테스트 데이터 셋 기준 평가 (v6.0)</span>
          </div>
          <button className="start-btn" onClick={onClose} style={{ padding: '0.5rem 1.5rem', fontSize: '0.9rem' }}>
            확인
          </button>
        </div>
      </div>

      <style>{`
        .dashboard-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          background: rgba(0, 0, 0, 0.7);
          backdrop-filter: blur(8px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          animation: fadeIn 0.3s ease-out;
        }

        .accomplishments-container {
          width: 800px;
          max-width: 90%;
          background: var(--bg-card);
          padding: 3rem;
          position: relative;
          display: flex;
          flex-direction: column;
          gap: 2.5rem;
          box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
          border: 1px solid rgba(255, 255, 255, 0.1);
          animation: slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .close-btn {
          position: absolute;
          top: 1.5rem;
          right: 1.5rem;
          background: transparent;
          border: none;
          color: var(--text-secondary);
          cursor: pointer;
          transition: color 0.2s;
        }
        .close-btn:hover { color: var(--text-primary); }

        .dashboard-header {
          display: flex;
          align-items: center;
          gap: 1.5rem;
        }
        .dashboard-header h2 { font-size: 2rem; margin-bottom: 0.2rem; }
        .dashboard-header p { color: var(--text-secondary); }

        .stats-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 1.5rem;
        }

        .stat-card {
          background: rgba(255, 255, 255, 0.03);
          padding: 1.5rem;
          border-radius: 8px;
          display: flex;
          align-items: center;
          gap: 1.5rem;
          transition: transform 0.2s;
        }
        .stat-card:hover { transform: translateY(-4px); background: rgba(255, 255, 255, 0.05); }

        .stat-icon-bg {
          width: 56px;
          height: 56px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .stat-info { display: flex; flexDirection: column; gap: 0.2rem; }
        .stat-label { font-size: 0.85rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-value { font-size: 1.8rem; font-weight: 800; color: var(--text-primary); }
        .stat-sub { font-size: 0.8rem; color: var(--text-secondary); }

        .highlights-section {
          background: rgba(0, 169, 224, 0.05);
          padding: 2rem;
          border-radius: 8px;
          border: 1px solid rgba(0, 169, 224, 0.1);
        }
        .highlights-section h3 { display: flex; align-items: center; gap: 0.5rem; font-size: 1.1rem; margin-bottom: 1.5rem; color: var(--accent-cyan); }
        
        .highlights-list { list-style: none; display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        .highlights-list li { 
          display: flex; 
          align-items: center; 
          gap: 0.75rem; 
          font-size: 0.95rem; 
          color: var(--text-primary); 
        }
        .list-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent-cyan); }

        .performance-footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-top: 1rem;
          border-top: 1px solid var(--border-color);
        }
        .footer-item { display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary); font-size: 0.85rem; }

        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { 
          from { opacity: 0; transform: translateY(20px); } 
          to { opacity: 1; transform: translateY(0); } 
        }
      `}</style>
    </div>
  );
};

export default AccomplishmentsDashboard;
