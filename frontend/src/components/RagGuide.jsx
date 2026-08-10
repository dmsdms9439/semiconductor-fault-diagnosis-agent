import React, { useState } from 'react';
import { BookOpen, Search, CheckCircle2, ChevronRight, GitMerge, AlertTriangle, Info } from 'lucide-react';

const RagGuide = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [ragResult, setRagResult] = useState(null);
  const [error, setError] = useState(null);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    
    setIsSearching(true);
    setRagResult(null);
    setError(null);
    
    try {
      const response = await fetch('/api/rag_search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query: searchQuery }),
      });
      
      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }
      
      const data = await response.json();
      setRagResult(data);
      setIsSearching(false);
    } catch (err) {
      console.error("RAG Search Error:", err);
      setError(err.message || "서버 연결에 실패했습니다.");
      setIsSearching(false);
    }
  };

  // Parse markdown-like text into JSX
  const renderMarkdown = (text) => {
    if (!text) return null;
    return text.split('\n').map((line, i) => {
      if (line.trim() === '') return <div key={i} style={{ height: '0.6rem' }} />;
      
      // Bold text (**text**)
      const parts = line.split(/(\*\*.*?\*\*)/g);
      return (
        <div key={i} style={{ marginBottom: '0.3rem', lineHeight: '1.7' }}>
          {parts.map((part, j) => {
            if (part.startsWith('**') && part.endsWith('**')) {
              return <strong key={j} style={{ color: 'var(--accent-cyan)' }}>{part.slice(2, -2)}</strong>;
            }
            return <span key={j}>{part}</span>;
          })}
        </div>
      );
    });
  };

  // Quick search templates
  const quickSearches = [
    "Vat Valve 이상 시 점검 절차는?",
    "TCP Top Power 이상 원인과 조치 방법은?",
    "He Chuck 압력 이상 시 SOP는?",
    "챔버 압력 드리프트 대응 방법은?",
  ];

  return (
    <div className="tab-content">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <BookOpen size={24} color="var(--accent-blue)" />
        <h2>Intelligent Maintenance Guide (GraphRAG)</h2>
      </div>

      {/* Search Bar */}
      <div className="glass-panel" style={{ marginBottom: '1.5rem' }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: '1rem' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={20} color="var(--text-secondary)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)' }} />
            <input 
              type="text" 
              className="select-input"
              style={{ paddingLeft: '3rem', fontSize: '1.05rem' }}
              placeholder="🔍 증상 검색 (예: S1P4 센서 압력 이상 시 조치 방법은?)"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <button 
            type="submit" 
            className="start-btn" 
            style={{ padding: '0 2rem', background: 'var(--accent-blue)' }}
            disabled={isSearching}
          >
            {isSearching ? 'Searching...' : 'Search'}
          </button>
        </form>

        {/* Quick Search Tags */}
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
          {quickSearches.map((q, i) => (
            <button
              key={i}
              onClick={() => { setSearchQuery(q); }}
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border-color)',
                borderRadius: '20px',
                padding: '0.4rem 1rem',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => { e.target.style.borderColor = 'var(--accent-cyan)'; e.target.style.color = 'var(--accent-cyan)'; }}
              onMouseOut={(e) => { e.target.style.borderColor = 'var(--border-color)'; e.target.style.color = 'var(--text-secondary)'; }}
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Loading State */}
      {isSearching && (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
          <GitMerge size={32} className="animate-pulse" style={{ animation: 'pulse 1.5s infinite', margin: '0 auto 1rem', color: 'var(--accent-blue)' }} />
          <p>Navigating Knowledge Graph...</p>
          <p style={{ fontSize: '0.85rem', marginTop: '0.5rem', color: 'var(--text-secondary)' }}>
            Neo4j 그래프 DB에서 관련 정비 매뉴얼을 검색하고 LLM으로 분석 중...
          </p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="glass-panel" style={{ border: '1px solid var(--accent-red)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <AlertTriangle size={24} color="var(--accent-red)" />
          <div>
            <h4 style={{ color: 'var(--accent-red)', marginBottom: '0.25rem' }}>연결 오류</h4>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              {error}
            </p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              💡 서버가 실행 중인지 확인하세요: <code style={{ color: 'var(--accent-cyan)' }}>python server.py</code>
            </p>
          </div>
        </div>
      )}

      {/* Results */}
      {ragResult && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '1.5rem', minHeight: '350px' }}>
          {/* 왼쪽: 검색 메타 정보 + 지식 그래프 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Query Info */}
            <div className="glass-panel">
              <h3 style={{ marginBottom: '0.8rem', fontSize: '1rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Info size={16} /> 검색 정보
              </h3>
              <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>
                <p style={{ marginBottom: '0.5rem' }}>
                  <strong style={{ color: 'var(--accent-cyan)' }}>질의:</strong> {searchQuery}
                </p>
                {ragResult.candidates && ragResult.candidates.length > 0 && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <strong style={{ color: 'var(--accent-cyan)' }}>매칭된 결함:</strong>
                    {ragResult.candidates.map((c, i) => (
                      <div key={i} style={{ 
                        margin: '0.3rem 0', 
                        padding: '0.4rem 0.8rem', 
                        background: 'rgba(0,169,224,0.1)',
                        borderRadius: '4px',
                        fontSize: '0.85rem'
                      }}>
                        {c.name} — Score: {(c.score * 100).toFixed(0)}%
                      </div>
                    ))}
                  </div>
                )}
                {ragResult.token_estimate > 0 && (
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                    Token usage: ~{ragResult.token_estimate}
                  </p>
                )}
              </div>
            </div>

            {/* Knowledge Graph Visualization */}
            <div className="glass-panel" style={{ flex: 1 }}>
              <h3 style={{ marginBottom: '0.8rem', fontSize: '1rem', color: 'var(--text-secondary)' }}>
                Knowledge Graph Path
              </h3>
              <div style={{ 
                flex: 1, 
                background: 'rgba(0,0,0,0.3)', 
                borderRadius: '8px', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center',
                border: '1px dashed var(--border-color)', 
                position: 'relative', 
                overflow: 'hidden',
                minHeight: '150px',
                padding: '1rem'
              }}>
                {ragResult.chain && ragResult.chain.fault_name ? (
                  <>
                    <div style={{ position: 'absolute', top: '15%', left: '15%', width: '55px', height: '55px', background: 'var(--accent-red)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.65rem', fontWeight: 'bold', textAlign: 'center', padding: '4px' }}>
                      {ragResult.chain.fault_name?.substring(0, 12)}
                    </div>
                    {ragResult.chain.components && ragResult.chain.components.filter(c => c).slice(0, 2).map((comp, i) => (
                      <div key={i} style={{ 
                        position: 'absolute', 
                        top: `${35 + i * 25}%`, 
                        left: `${45 + i * 10}%`, 
                        width: '50px', height: '50px', 
                        background: i === 0 ? 'var(--accent-cyan)' : 'var(--accent-blue)', 
                        borderRadius: '50%', 
                        display: 'flex', alignItems: 'center', justifyContent: 'center', 
                        fontSize: '0.6rem', fontWeight: 'bold', textAlign: 'center', padding: '4px' 
                      }}>
                        {comp.substring(0, 10)}
                      </div>
                    ))}
                    <div style={{ position: 'absolute', bottom: '10%', right: '15%', width: '55px', height: '55px', background: 'var(--accent-green)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6rem', fontWeight: 'bold', textAlign: 'center', padding: '4px' }}>
                      SOP<br/>Action
                    </div>
                    <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: -1 }}>
                      <line x1="20%" y1="20%" x2="50%" y2="50%" stroke="rgba(255,255,255,0.2)" strokeWidth="2" strokeDasharray="5,5" />
                      <line x1="50%" y1="50%" x2="80%" y2="80%" stroke="rgba(255,255,255,0.2)" strokeWidth="2" strokeDasharray="5,5" />
                    </svg>
                  </>
                ) : (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                    <GitMerge size={32} style={{ marginBottom: '0.5rem', opacity: 0.3 }} />
                    <p>그래프 경로 정보 없음</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 오른쪽: AI 정비 가이드 (실제 RAG 응답) */}
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <h3 style={{ marginBottom: '1rem', fontSize: '1rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <CheckCircle2 size={18} color="var(--accent-green)" />
              AI 정비 가이드 (GraphRAG + LLM)
            </h3>
            <div style={{ 
              flex: 1, 
              background: 'rgba(0,0,0,0.3)', 
              borderRadius: '8px', 
              padding: '1.5rem',
              border: '1px solid var(--border-color)',
              overflowY: 'auto',
              fontFamily: 'inherit',
              fontSize: '0.95rem',
              lineHeight: '1.8',
              color: 'var(--text-primary)',
            }}>
              {ragResult.recommendation ? (
                renderMarkdown(ragResult.recommendation)
              ) : (
                <div style={{ color: 'var(--text-secondary)', textAlign: 'center', paddingTop: '2rem' }}>
                  응답을 생성할 수 없습니다.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isSearching && !ragResult && !error && (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <BookOpen size={48} style={{ color: 'var(--text-secondary)', opacity: 0.3, marginBottom: '1rem' }} />
          <p style={{ color: 'var(--text-secondary)', fontSize: '1rem' }}>
            위 검색창에 질문을 입력하여 Neo4j Knowledge Graph 기반 정비 가이드를 검색하세요.
          </p>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.5rem' }}>
            또는 아래 빠른 검색 태그를 클릭하세요.
          </p>
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.1); }
          100% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
};

export default RagGuide;
