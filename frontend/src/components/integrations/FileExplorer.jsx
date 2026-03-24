import React, { useState, useEffect, useRef, useCallback } from "react";
import { summarizationApi } from "../../services/summarizationApi";

const AssistantSuggestions = ({ questions, onQuery, loading, contextFile }) => {
    const [showAll, setShowAll] = useState(false);
    
    useEffect(() => {
        const styleId = "gemini-suggestions-style";
        if (!document.getElementById(styleId)) {
            const style = document.createElement("style");
            style.id = styleId;
            style.innerHTML = `
                .gemini-suggestion {
                    background-color: transparent !important;
                    transition: all 0.2s ease !important;
                    border: none !important;
                    outline: none !important;
                }
                .gemini-suggestion:hover:not(:disabled) {
                    background-color: rgba(255, 255, 255, 0.08) !important;
                }
                .gemini-suggestion:active:not(:disabled) {
                    background-color: rgba(255, 255, 255, 0.15) !important;
                    transform: scale(0.98);
                }
                .gemini-suggestion-toggle:hover {
                    background-color: rgba(255, 255, 255, 0.05) !important;
                    color: #E2E8F0 !important;
                }
            `;
            document.head.appendChild(style);
        }
    }, []);

    if (!questions || questions.length === 0) return null;

    const displayedQuestions = showAll ? questions : questions.slice(0, 3);

    return (
        <div style={{ 
            marginTop: "1.5rem", 
            marginBottom: "1rem",
            display: "flex",
            flexDirection: "column",
            gap: "2px"
        }}>
            {displayedQuestions.map((q, idx) => {
                const questionText = typeof q === "string" ? q : (q?.text || q?.question || JSON.stringify(q) || "");
                return (
                <button 
                    key={idx} 
                    className="gemini-suggestion"
                    type="button"
                    onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (!loading && questionText) onQuery(questionText, contextFile);
                    }}
                    disabled={loading}
                    style={{
                        textAlign: "left",
                        padding: "10px 12px",
                        color: "#E2E8F0",
                        borderRadius: "8px",
                        cursor: loading ? "wait" : "pointer",
                        fontSize: "0.9rem",
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "14px",
                        width: "100%",
                        lineHeight: "1.5",
                        opacity: loading ? 0.6 : 1,
                        pointerEvents: "auto",
                        position: "relative",
                        zIndex: 10
                    }}
                >
                    <span style={{ 
                        color: "#94A3B8", 
                        fontSize: "1.2rem", 
                        marginTop: "2px",
                        display: "inline-block",
                        transform: "scaleX(-1)"
                    }}>
                        ↳
                    </span>
                    <span style={{ flex: 1 }}>{questionText}</span>
                </button>
                );
            })}
            
            {questions.length > 3 && (
                <button 
                    className="gemini-suggestion-toggle"
                    type="button"
                    onClick={() => setShowAll(!showAll)}
                    style={{
                        marginTop: "4px",
                        background: "none",
                        border: "none",
                        color: "#94A3B8",
                        fontSize: "0.85rem",
                        cursor: "pointer",
                        padding: "8px 12px",
                        borderRadius: "8px",
                        transition: "all 0.2s",
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        width: "fit-content"
                    }}
                >
                    <span style={{ fontSize: "1.1rem" }}>{showAll ? "✨" : "🪄"}</span>
                    {showAll ? "Show fewer suggestions" : `Show ${questions.length - 3} more suggestions`}
                </button>
            )}
        </div>
    );
};

const FileExplorer = ({ onClose, folderName, folderId }) => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [suggestions, setSuggestions] = useState([]);
    const [showSuggestions, setShowSuggestions] = useState(false);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    useEffect(() => {
        summarizationApi.getStatus().catch(() => {});
    }, []);

    // Auto-scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // If opened with a folder context, auto-populate
    useEffect(() => {
        if (folderName && folderId) {
            setInput(`summarize @"${folderName}"`);
        }
    }, [folderName, folderId]);

    const handleAutocomplete = useCallback(async (text) => {
        if (!text.trim() || loading) {
            setShowSuggestions(false);
            setSuggestions([]);
            return;
        }
        const atMatch = text.match(/@(\S*)$/);
        if (atMatch) {
            try {
                const results = await summarizationApi.autocomplete(atMatch[1]);
                setSuggestions(results);
                setShowSuggestions(results.length > 0);
            } catch { 
                setSuggestions([]); 
                setShowSuggestions(false);
            }
        } else {
            setShowSuggestions(false);
        }
    }, [loading]);

    const handleInputChange = (e) => {
        const val = e.target.value;
        setInput(val);
        handleAutocomplete(val);
    };

    const insertMention = (item) => {
        const before = input.replace(/@\S*$/, "");
        const name = item.name.includes(" ") ? `@"${item.name}"` : `@${item.name}`;
        setInput(before + name + " ");
        setShowSuggestions(false);
        inputRef.current?.focus();
    };

    const handleSend = async (overrideMsg, contextFile = null) => {
        let userMsg = (typeof overrideMsg === "string" ? overrideMsg : input).trim();
        if (!userMsg || loading) return;

        // Auto-inject context for suggestions (Requirement: Click Behavior)
        if (typeof overrideMsg === "string" && !userMsg.includes("@")) {
            const targetContext = contextFile || folderName;
            if (targetContext) {
                const contextMention = targetContext.includes(" ") ? `@"${targetContext}"` : `@${targetContext}`;
                userMsg = `${userMsg} ${contextMention}`;
            }
        }
        setShowSuggestions(false);
        setSuggestions([]);
        
        setMessages(prev => [...prev, { role: "user", content: userMsg }]);
        setLoading(true);

        try {
            const response = await summarizationApi.query(userMsg);
            setMessages(prev => [...prev, {
                role: "assistant",
                content: response.answer,
                sources: response.sources,
                intent: response.intent,
                type: response.type,
            }]);
        } catch (err) {
            const detail = err?.response?.data?.detail || err.message || "Something went wrong.";
            setMessages(prev => [...prev, {
                role: "assistant",
                content: `❌ Error: ${detail}`,
                sources: [],
            }]);
        } finally {
            setLoading(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleQuickIngest = async () => {
        if (!folderId) return;
        setLoading(true);
        setMessages(prev => [...prev, { role: "system", content: `📂 Indexing folder "${folderName}" for AI analysis...` }]);
        try {
            const result = await summarizationApi.ingestFolder(folderId);
            setMessages(prev => [...prev, {
                role: "system",
                content: `✅ Indexed ${result.details?.indexed || 0} of ${result.details?.total_files || 0} files successfully.`
            }]);
        } catch (err) {
            setMessages(prev => [...prev, { role: "system", content: `❌ Indexing failed: ${err.message}` }]);
        } finally {
            setLoading(false);
        }
    };

    const renderAssistantContent = (msg) => {
        const isLegal = msg.type === "legal_case";
        const rawContent = msg.content || "";
        
        let summary = rawContent;
        let questionsList = [];

        try {
            if (typeof rawContent === "object" && rawContent !== null) {
                summary = rawContent.summary || "";
                questionsList = rawContent.suggested_questions || [];
            } else {
                let jsonStr = rawContent.trim();

                jsonStr = jsonStr.replace(/```json\s?([\s\S]*?)```/g, "$1").trim();
                
                if (!jsonStr.startsWith("{")) {
                    const firstBrace = jsonStr.indexOf("{");
                    const lastBrace = jsonStr.lastIndexOf("}");
                    if (firstBrace !== -1 && lastBrace !== -1) {
                        jsonStr = jsonStr.substring(firstBrace, lastBrace + 1);
                    }
                }

                const data = JSON.parse(jsonStr);
                // If summary is empty, show a fallback message rather than the raw JSON string
                summary = (data.summary && data.summary.trim()) ? data.summary : (data.summary === "" ? "Summary could not be generated." : rawContent);
                questionsList = data.suggested_questions || [];
            }
        } catch (err) {
            console.warn("JSON parse failed, falling back to regex", err);
            // Fallback 
            const parts = typeof rawContent === "string" ? rawContent.split("### Suggested Questions") : ["", ""];
            summary = parts[0] || (typeof rawContent === "string" ? rawContent : "");
            const questionsRaw = parts[1] || "";
            
            questionsList = questionsRaw
                .split(/\n/)
                .map(q => q.replace(/^[-1-9.\s]+/, "").trim())
                .filter(q => q.length > 5);
        }

        return (
            <>
                <div style={{ 
                    fontSize: "0.7rem", 
                    color: isLegal ? "#f6ad55" : "#667eea", 
                    fontWeight: "bold", 
                    marginBottom: msg.type ? "10px" : "6px", 
                    textTransform: "uppercase",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px"
                }}>
                    {isLegal ? "⚖️ Legal Case Analysis" : msg.type === "general_document" ? "📄 General Document Analysis" : "🤖 AI Response"}
                    {msg.type && (
                        <span style={{ 
                            fontSize: "0.6rem", 
                            background: isLegal ? "rgba(246, 173, 85, 0.1)" : "rgba(102, 126, 234, 0.1)", 
                            padding: "2px 8px", 
                            borderRadius: "12px", 
                            marginLeft: "auto",
                            border: `1px solid ${isLegal ? "rgba(246, 173, 85, 0.3)" : "rgba(102, 126, 234, 0.3)"}`
                        }}>
                            High Precision
                        </span>
                    )}
                </div>
                
                <div style={{ color: "#E2E8F0", whiteSpace: "pre-wrap" }}>
                    {summary}
                </div>

                <AssistantSuggestions 
                    questions={questionsList} 
                    onQuery={(q, cf) => handleSend(q, cf)} 
                    loading={loading}
                    contextFile={msg.sources && msg.sources.length > 0 ? msg.sources[0].file : null}
                />
            </>
        );
    };

    return (
        <div style={{ width: "100%", height: "calc(100vh - 40px)", minHeight: "600px", background: "#1E293B", borderRadius: "16px", border: "1px solid rgba(255,255,255,0.1)", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "rgba(0, 0, 0, 0.3) 0px 10px 30px" }}>
            {/* Header */}
            <div style={{ padding: "16px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid rgba(255,255,255,0.1)", background: "rgba(102, 126, 234, 0.1)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{ fontSize: "1.5rem" }}></span>
                    <div>
                        <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#F7FAFC" }}>AI Document Analyzer</h3>
                        {folderName && (
                            <div style={{ fontSize: "0.8rem", color: "#A0AEC0", marginTop: "4px" }}>
                                Querying: <span style={{ color: "#667eea", fontWeight: "600" }}>{folderName}</span>
                            </div>
                        )}
                    </div>
                </div>
                <button onClick={onClose} style={{
                    background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
                    color: "#A0AEC0", borderRadius: "10px", padding: "8px 16px", cursor: "pointer",
                    fontSize: "0.85rem", transition: "all 0.2s"
                }}>✕ Close</button>
            </div>

            {/* Messages Area */}
            <div style={{
                flex: 1, overflowY: "auto", padding: "20px 25px",
                display: "flex", flexDirection: "column", gap: "16px"
            }}>
                {messages.length === 0 && (
                    <div style={{ textAlign: "center", padding: "40px 20px", color: "#718096" }}>
                        <div style={{ fontSize: "3rem", marginBottom: "15px", opacity: 0.5 }}>🔍</div>
                        <h4 style={{ color: "#A0AEC0", margin: "0 0 10px 0" }}>Ask anything about your files</h4>
                        <p style={{ fontSize: "0.9rem", lineHeight: 1.6 }}>
                            Use <code style={{ background: "rgba(102,126,234,0.2)", padding: "2px 8px", borderRadius: "4px", color: "#667eea" }}>@mention</code> to reference files or folders.
                        </p>
                        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "20px", alignItems: "center" }}>
                            {[
                                `summarize @"${folderName || "FolderName"}"`,
                                `what are the key findings in @"${folderName || "FolderName"}"?`,
                            ].map((example, i) => (
                                <button key={i} onClick={() => setInput(example)} style={{
                                    background: "rgba(102,126,234,0.08)", border: "1px solid rgba(102,126,234,0.2)",
                                    color: "#A0AEC0", borderRadius: "8px", padding: "8px 16px", cursor: "pointer",
                                    fontSize: "0.8rem", transition: "all 0.2s", maxWidth: "400px"
                                }}>{example}</button>
                            ))}
                        </div>
                        {folderId && (
                            <button onClick={handleQuickIngest} style={{
                                marginTop: "20px", background: "rgba(72,187,120,0.15)",
                                border: "1px solid rgba(72,187,120,0.3)", color: "#48bb78",
                                borderRadius: "10px", padding: "10px 20px", cursor: "pointer", fontSize: "0.85rem"
                            }}>📂 Index "{folderName}" for AI</button>
                        )}
                    </div>
                )}

                {messages.map((msg, i) => (
                    <div key={i} style={{
                        display: "flex",
                        justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                    }}>
                        <div style={{
                            maxWidth: msg.role === "system" ? "100%" : "85%",
                            padding: msg.role === "system" ? "10px 16px" : "14px 18px",
                            borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                            background: msg.role === "user"
                                ? "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
                                : msg.role === "system"
                                    ? "rgba(72,187,120,0.1)"
                                    : "rgba(255,255,255,0.05)",
                            border: msg.role === "system"
                                ? "1px solid rgba(72,187,120,0.2)"
                                : msg.role === "assistant"
                                    ? "1px solid rgba(255,255,255,0.08)"
                                    : "none",
                            color: "#E2E8F0",
                            fontSize: msg.role === "system" ? "0.8rem" : "0.9rem",
                            lineHeight: 1.7,
                            wordBreak: "break-word",
                        }}>
                            {msg.role === "assistant" ? renderAssistantContent(msg) : msg.content}
                            {msg.sources && msg.sources.length > 0 && (
                                <div style={{
                                    marginTop: "12px", paddingTop: "10px",
                                    borderTop: "1px solid rgba(255,255,255,0.06)", fontSize: "0.75rem", color: "#718096"
                                }}>
                                    📎 Sources: {msg.sources.map(s => s.file).join(", ")}
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {loading && (
                    <div style={{ display: "flex", justifyContent: "flex-start" }}>
                        <div style={{
                            padding: "14px 18px", borderRadius: "16px 16px 16px 4px",
                            background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)",
                            color: "#A0AEC0", fontSize: "0.9rem"
                        }}>
                            <span className="typing-dots">Analyzing documents</span>
                            <span style={{ animation: "pulse 1.5s infinite" }}> ...</span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div style={{
                padding: "18px 25px", borderTop: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(0,0,0,0.2)", position: "relative"
            }}>
                {/* Autocomplete dropdown */}
                {showSuggestions && suggestions.length > 0 && (
                    <div style={{
                        position: "absolute", bottom: "100%", left: "25px", right: "25px",
                        background: "rgba(26,32,44,0.98)", border: "1px solid rgba(102,126,234,0.3)",
                        borderRadius: "12px", overflow: "hidden", boxShadow: "0 -8px 30px rgba(0,0,0,0.4)",
                        maxHeight: "200px", overflowY: "auto", zIndex: 10
                    }}>
                        {suggestions.map((item, i) => (
                            <div key={i} onClick={() => insertMention(item)} style={{
                                padding: "10px 16px", cursor: "pointer", display: "flex", alignItems: "center", gap: "10px",
                                borderBottom: "1px solid rgba(255,255,255,0.04)", transition: "background 0.15s",
                                color: "#E2E8F0", fontSize: "0.85rem"
                            }}
                            onMouseOver={e => e.currentTarget.style.background = "rgba(102,126,234,0.1)"}
                            onMouseOut={e => e.currentTarget.style.background = "transparent"}
                            >
                                <span>{item.type === "folder" ? "📁" : "📄"}</span>
                                <span>{item.name}</span>
                                <span style={{ marginLeft: "auto", fontSize: "0.7rem", color: "#718096" }}>{item.type}</span>
                            </div>
                        ))}
                    </div>
                )}

                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                    <input
                        ref={inputRef}
                        type="text"
                        value={input}
                        onChange={handleInputChange}
                        onKeyDown={handleKeyDown}
                        placeholder='Type "summarize @folder-name" or ask a question...'
                        disabled={loading}
                        style={{
                            flex: 1, padding: "14px 18px",
                            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
                            borderRadius: "12px", color: "white", fontSize: "0.9rem",
                            outline: "none", transition: "border 0.2s"
                        }}
                        onFocus={e => e.target.style.borderColor = "rgba(102,126,234,0.5)"}
                        onBlur={e => e.target.style.borderColor = "rgba(255,255,255,0.1)"}
                    />
                    <button
                        onClick={handleSend}
                        disabled={loading || !input.trim()}
                        style={{
                            padding: "14px 22px", borderRadius: "12px",
                            background: loading || !input.trim()
                                ? "rgba(255,255,255,0.05)"
                                : "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                            border: "none", color: "white", cursor: loading ? "wait" : "pointer",
                            fontSize: "0.9rem", fontWeight: "bold", transition: "all 0.2s",
                            opacity: loading || !input.trim() ? 0.5 : 1
                        }}
                    >
                        {loading ? "⏳" : "Send"}
                    </button>
                </div>
            </div>

            <style>{`
                @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
            `}</style>
        </div>
    );
};

export default FileExplorer;
