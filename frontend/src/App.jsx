import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Play, Square, Activity, BrainCircuit, BookOpen, LayoutDashboard, Settings, Wifi, WifiOff } from 'lucide-react';
import './App.css';
import LiveDashboard from './LiveDashboard';
import ShapExplainer from './components/ShapExplainer';
import RagGuide from './components/RagGuide';
import FleetOverview from './components/FleetOverview';
import AccomplishmentsDashboard from './components/AccomplishmentsDashboard';
import { BarChart3 } from 'lucide-react';

function App() {
  const [activeTab, setActiveTab] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [showAccomplishments, setShowAccomplishments] = useState(false);
  const [selectedModel] = useState("식각 공정 이상 감지 통합 모델 v1.0");
  
  // 데이터 소스 선택
  const [dataSource, setDataSource] = useState('local'); // 'local' or 'kafka'
  const [slackEnabled, setSlackEnabled] = useState(true);
  const [streamSpeed, setStreamSpeed] = useState(0.5);
  
  // WebSocket 연결 상태
  const [wsConnected, setWsConnected] = useState(false);
  
  // 전역 데이터 상태 (다중 장비 지원)
  const [fleetStatus, setFleetStatus] = useState({});
  const [metricsHistory, setMetricsHistory] = useState({});
  const [shapHistory, setShapHistory] = useState({});
  
  const [selectedEquipment, setSelectedEquipment] = useState('EQ-01');
  const [selectedShapTime, setSelectedShapTime] = useState(null);
  const wsRef = React.useRef(null);

  // 시스템 상태
  const [systemStatus, setSystemStatus] = useState(null);

  const handleSelectEquipment = (eqId) => {
    setSelectedEquipment(eqId);
    setActiveTab(1); // 개별 설비 모니터링 탭으로 이동
  };

  const handleAnomalyClick = (time) => {
    setSelectedShapTime(time);
    setActiveTab(2); // 이상 원인 분석 탭으로 이동
  };

  // Fetch system status on mount
  React.useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch('/api/system_status');
        if (res.ok) {
          const data = await res.json();
          setSystemStatus(data);
        }
      } catch (err) {
        console.log('Server not available yet:', err.message);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  // WebSocket connection
  // WebSocket connection
  useEffect(() => {
    // 시스템이 정지된 경우 소켓 닫기
    if (!isRunning) {
      if (wsRef.current) {
        console.log("🔌 Stopping WebSocket connection...");
        wsRef.current.close();
        wsRef.current = null;
      }
      setWsConnected(false);
      return;
    }

    // 시스템 가동 시 기존 기록 초기화 (메모리 확보 및 신선도 유지)
    console.log("🧹 Clearing history for fresh start...");
    setMetricsHistory({});
    setShapHistory({});
    setFleetStatus({});

    // Build WebSocket URL
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    const params = new URLSearchParams({
      source: dataSource,
      speed: streamSpeed.toString(),
      slack: slackEnabled.toString(),
    });
    const wsUrl = `${wsProtocol}//${wsHost}/ws/stream?${params.toString()}`;
    
    console.log(`🔗 Connecting WebSocket: ${wsUrl}`);
    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      console.log('✅ WebSocket connected');
      setWsConnected(true);
    };

    socket.onclose = (e) => {
      console.log(`🔌 WebSocket closed: ${e.code} ${e.reason}`);
      setWsConnected(false);
    };

    socket.onerror = (e) => {
      console.error('❌ WebSocket error:', e);
      setWsConnected(false);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const eqId = payload.equipment_id;
        if (!eqId) return;

        if (payload.type === 'metrics') {
          // 1. 실시간 상태 업데이트 (Batching)
          setFleetStatus(prev => ({
            ...prev,
            [eqId]: payload
          }));
          
          // 2. 메트릭 히스토리 업데이트 (최대 200개 제한)
          setMetricsHistory(prev => {
            const eqHistory = prev[eqId] || [];
            const newData = [...eqHistory, { time: payload.time, mse: payload.mse, is_anomaly: payload.is_anomaly }];
            return {
              ...prev,
              [eqId]: newData.length > 200 ? newData.slice(1) : newData
            };
          });
        } else if (payload.type === 'shap_data') {
          const formatted = payload.analysis_data.map(item => ({
            name: item.sensor,
            value: Math.abs(item.shap_value)
          })).sort((a, b) => b.value - a.value).slice(0, 8);
          
          setShapHistory(prev => {
            const eqShap = prev[eqId] || {};
            const newEqShap = {
              ...eqShap,
              [payload.time]: { 
                data: formatted, 
                explanation: "분석 중...",
                recommendation: "",
                fault_status: payload.fault_status
              }
            };
            
            // [메모리 최적화] SHAP 히스토리 개수 제한 (최신 50개)
            const times = Object.keys(newEqShap).sort();
            if (times.length > 50) {
              delete newEqShap[times[0]];
            }
            
            return {
              ...prev,
              [eqId]: newEqShap
            };
          });
          
          // 현재 선택된 장비라면 자동 포커스 (Ref 사용 고려 가능하나 현재는 상태로 유지)
          // selectedEquipment는 ref가 아니므로 최신값을 읽기 위해 closure issue 주의
          // 하지만 setSelectedShapTime은 비동기 상태 업데이트이므로 안전함
          setSelectedShapTime(payload.time);
        } else if (payload.type === 'shap_report') {
          setShapHistory(prev => {
            const eqShap = prev[eqId] || {};
            if (!eqShap[payload.time]) return prev;
            
            return {
              ...prev,
              [eqId]: {
                ...eqShap,
                [payload.time]: { 
                  ...eqShap[payload.time], 
                  explanation: payload.explanation,
                  recommendation: payload.recommendation,
                  top_candidates: payload.top_candidates || []
                }
              }
            };
          });
        } else if (payload.type === 'equipment_stop') {
          // 설비 정지 상태 업데이트
          setFleetStatus(prev => ({
            ...prev,
            [eqId]: { 
              ...prev[eqId], 
              status: '🚨 정지됨 (이상 감지)', 
              is_anomaly: true,
              message: payload.message 
            }
          }));
        } else if (payload.type === 'alert') {
          console.log(`⚡ Phase 1 Alert: ${payload.message}`);
          // 설비 상태를 즉시 '이상 감지(진단 중...)'으로 업데이트하여 사용자에게 알림
          setFleetStatus(prev => ({
            ...prev,
            [eqId]: { 
              ...prev[eqId], 
              status: '🚨 이상 감지 (원인 분석 중...)', 
              is_anomaly: true 
            }
          }));
        } else if (payload.type === 'info') {
          console.info('System info:', payload.message);
          // 알림창 등을 띄울 수도 있음
        } else if (payload.type === 'error') {
          console.error('Server error:', payload.message);
        }
      } catch (err) {
        console.error("Failed to parse WS message:", err);
      }
    };

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [isRunning, dataSource, streamSpeed, slackEnabled]); // selectedEquipment 제외하여 재연결 방지


  const tabs = [
    { id: 0, label: "전체 설비 현황", icon: LayoutDashboard },
    { id: 1, label: "개별 설비 모니터링", icon: Activity },
    { id: 2, label: "이상 원인 분석 (SHAP)", icon: BrainCircuit },
    { id: 3, label: "정비 가이드 (RAG)", icon: BookOpen },
  ];

  return (
    <div className="app-container" style={{ flexDirection: 'column' }}>
      {/* Global Dashboard Header */}
      <header style={{ 
        background: 'var(--bg-card)', 
        borderBottom: '1px solid var(--border-color)',
        zIndex: 10
      }}>
        {/* Top Row: Title and Controls */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.5rem 2rem' }}>
          {/* Left: Title */}
          <div>
            <div style={{ color: 'var(--accent-cyan)', fontSize: '0.85rem', fontWeight: 'bold', marginBottom: '0.3rem', letterSpacing: '1px' }}>SMART FACTORY</div>
            <h1 style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--text-primary)', letterSpacing: '0.5px' }}>
              반도체 식각 공정 지능형 관제 에이전트
            </h1>
          </div>

          {/* Right: Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            {/* Connection Status */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
              {wsConnected ? (
                <>
                  <Wifi size={16} color="var(--accent-green)" />
                  <span style={{ color: 'var(--accent-green)' }}>연결됨</span>
                </>
              ) : (
                <>
                  <WifiOff size={16} color="var(--text-secondary)" />
                  <span style={{ color: 'var(--text-secondary)' }}>대기</span>
                </>
              )}
            </div>

            {/* Data Source Select */}
            <select
              value={dataSource}
              onChange={(e) => setDataSource(e.target.value)}
              className="select-input"
              style={{ width: '140px', padding: '0.5rem 0.75rem', fontSize: '0.85rem' }}
              disabled={isRunning}
            >
              <option value="local">📁 Local CSV</option>
              <option value="kafka">📡 Kafka Stream</option>
            </select>

            {/* Slack Toggle */}
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <input 
                type="checkbox" 
                checked={slackEnabled} 
                onChange={(e) => setSlackEnabled(e.target.checked)} 
                style={{ accentColor: 'var(--accent-cyan)' }}
                disabled={isRunning}
              />
              Slack
            </label>

            {/* Model Info */}
            <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ color: 'var(--accent-green)' }}>●</span> {selectedModel}
            </div>
            
            <button 
              className="start-btn"
              style={{ background: 'rgba(0, 169, 224, 0.1)', border: '1px solid var(--accent-cyan)', color: 'var(--accent-cyan)', padding: '0.8rem 1.2rem' }}
              onClick={() => setShowAccomplishments(true)}
            >
              <BarChart3 size={18} /> Analyze
            </button>

            <button 
              className={`start-btn ${isRunning ? 'running' : ''}`}
              style={{ padding: '0.8rem 1.5rem', borderRadius: '4px', fontSize: '1rem' }}
              onClick={() => setIsRunning(!isRunning)}
            >
              {isRunning ? <><Square size={18} /> 시스템 정지</> : <><Play size={18} fill="currentColor" /> 시스템 가동</>}
            </button>
          </div>
        </div>

        {/* Bottom Row: Tabs */}
        <div style={{ display: 'flex', gap: '1rem', padding: '0 2rem' }}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <div 
                key={tab.id}
                style={{ 
                  display: 'flex', alignItems: 'center', gap: '0.5rem', 
                  padding: '0.8rem 1.5rem', cursor: 'pointer', 
                  color: activeTab === tab.id ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                  borderBottom: activeTab === tab.id ? '3px solid var(--accent-cyan)' : '3px solid transparent',
                  fontWeight: activeTab === tab.id ? 'bold' : 'normal',
                  transition: 'all 0.2s',
                  fontSize: '1.05rem'
                }}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={20} />
                {tab.label}
              </div>
            );
          })}
          
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '1rem', paddingRight: '1rem' }}>
             <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>현재 선택된 장비: <strong style={{ color: 'var(--accent-cyan)', fontSize: '1.1rem' }}>{selectedEquipment}</strong></span>
             {systemStatus && (
               <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                 | 서버: <span style={{ color: 'var(--accent-green)' }}>{systemStatus.status}</span>
                 | 연결: {systemStatus.active_connections}
               </span>
             )}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="main-content" style={{ flex: 1, overflowY: 'auto', padding: '0' }}>
        {activeTab === 0 && (
          <FleetOverview fleetStatus={fleetStatus} onSelectEquipment={handleSelectEquipment} />
        )}

        {activeTab === 1 && (
          <LiveDashboard 
            latestMetrics={fleetStatus[selectedEquipment] || { mse: 0, status: '대기 중', confidence: 0, is_anomaly: false }} 
            metricsHistory={metricsHistory[selectedEquipment] || []} 
            isRunning={isRunning} 
            selectedModel={selectedModel} 
            onAnomalyClick={handleAnomalyClick} 
            equipmentId={selectedEquipment}
            topCandidates={fleetStatus[selectedEquipment]?.top_candidates || []}
          />
        )}
        
        {activeTab === 2 && (() => {
          const eqShapHistory = shapHistory[selectedEquipment] || {};
          const currentShap = eqShapHistory[selectedShapTime] || { data: [], explanation: "", top_candidates: [] };
          return (
            <ShapExplainer 
              shapHistory={eqShapHistory} 
              shapData={currentShap.data} 
              explanation={currentShap.explanation} 
              topCandidates={currentShap.top_candidates}
              isRunning={isRunning} 
              onSelectAnomaly={setSelectedShapTime} 
              selectedEquipment={selectedEquipment}
            />
          );
        })()}

        {activeTab === 3 && <RagGuide />}
      </main>

      {showAccomplishments && (
        <AccomplishmentsDashboard onClose={() => setShowAccomplishments(false)} />
      )}
    </div>
  );
}

export default App;
