import { useEffect, useMemo, useState } from 'react';

const BACKEND_URL = '';
const GOOGLE_API_KEY = import.meta.env.VITE_GOOGLE_API_KEY || '';

// Basic primary and secondary colors
const COLORS = ['#FF0000', '#00CC00', '#0066FF', '#FFFF00', '#00FFFF', '#FF00FF', '#FF6600', '#9933FF', '#FF3366', '#00FF99'];

const getTaxiColor = (taxi) => {
  const index = Number(taxi) % COLORS.length;
  return COLORS[index];
};

function App() {
  const [file, setFile] = useState(null);
  const [timeFilter, setTimeFilter] = useState('');
  const [typeCourseFilter, setTypeCourseFilter] = useState('');
  const [operationFilter, setOperationFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [groupedData, setGroupedData] = useState([]);
  const [stats, setStats] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [validation, setValidation] = useState(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [validateMessage, setValidateMessage] = useState('');
  const [error, setError] = useState('');
  const [googleSignedIn, setGoogleSignedIn] = useState(false);
  const [authMessage, setAuthMessage] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [resultsSheetUrl, setResultsSheetUrl] = useState('');
  const [resultsSheetId, setResultsSheetId] = useState('');
  const [selectedSpreadsheetTitle, setSelectedSpreadsheetTitle] = useState('');
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [availableTimes, setAvailableTimes] = useState([]);
  const [availableOperations, setAvailableOperations] = useState([]);
  const [location, setLocation] = useState('Lac 2');
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetInfoLoaded, setSheetInfoLoaded] = useState(false);
  const [saveDriveLoading, setSaveDriveLoading] = useState(false);
  const [savedDriveUrl, setSavedDriveUrl] = useState('');
  const [saveDriveMessage, setSaveDriveMessage] = useState('');

  const sheetEmbedUrl = useMemo(() => {
    if (!resultsSheetUrl && !resultsSheetId) return '';
    const baseUrl = resultsSheetUrl || `https://docs.google.com/spreadsheets/d/${resultsSheetId}/edit`;
    try {
      const url = new URL(baseUrl);
      // Remove non-standard widget parameter if present
      url.searchParams.delete('widget');
      // Set standard embed parameters
      url.searchParams.set('usp', 'sharing');
      url.searchParams.set('rm', 'minimal');
      url.searchParams.set('headers', 'false');
      // Preserve hash (gid parameter) if present
      return url.toString();
    } catch {
      // Fallback for invalid URLs: preserve hash and add parameters before it
      const hashIndex = baseUrl.indexOf('#');
      if (hashIndex >= 0) {
        const beforeHash = baseUrl.substring(0, hashIndex);
        const hash = baseUrl.substring(hashIndex);
        const separator = beforeHash.includes('?') ? '&' : '?';
        return `${beforeHash}${separator}usp=sharing&rm=minimal&headers=false${hash}`;
      }
      return `${baseUrl}?usp=sharing&rm=minimal&headers=false`;
    }
  }, [resultsSheetUrl, resultsSheetId]);

  const sheetOpenUrl = useMemo(() => {
    return resultsSheetUrl || (resultsSheetId ? `https://docs.google.com/spreadsheets/d/${resultsSheetId}/edit` : '');
  }, [resultsSheetUrl, resultsSheetId]);

  const groupedByTaxi = useMemo(() => {
    if (!groupedData.length) return {};
    return groupedData.reduce((acc, row) => {
      const taxi = row['Groupe Taxi'] ?? row['Taxi'] ?? 'Unknown';
      if (!acc[taxi]) acc[taxi] = [];
      acc[taxi].push(row);
      return acc;
    }, {});
  }, [groupedData]);

  const activeStep = useMemo(() => {
    if (groupedData.length) return 'results';
    if (resultsSheetId || file) return 'configure';
    return 'source';
  }, [groupedData.length, resultsSheetId, file]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth') === 'success') {
      setAuthMessage('Signed in successfully. You can now choose a spreadsheet.');
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (params.get('auth') === 'error') {
      setAuthMessage(`Google sign-in failed: ${params.get('message') || 'unknown error'}`);
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    fetchAuthStatus();

    const savedSheetId = localStorage.getItem('taxi_grouper_active_sheet_id');
    const savedSheetTitle = localStorage.getItem('taxi_grouper_active_sheet_title');
    if (savedSheetId && savedSheetTitle) {
      setResultsSheetId(savedSheetId);
      setSelectedSpreadsheetTitle(savedSheetTitle);
    }
  }, []);

  useEffect(() => {
    if (googleSignedIn && resultsSheetId && !sheetInfoLoaded && !sheetLoading) {
      loadSheetInfo(resultsSheetId, selectedSpreadsheetTitle || 'Google Sheet', true);
    }
  }, [googleSignedIn, resultsSheetId, selectedSpreadsheetTitle, sheetInfoLoaded, sheetLoading]);

  const fetchAuthStatus = async () => {
    setAuthLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/status`);
      if (!response.ok) {
        throw new Error('Could not retrieve Google auth status.');
      }
      const data = await response.json();
      setGoogleSignedIn(Boolean(data.signed_in));
    } catch (err) {
      setError(err.message);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError('');
    setAuthLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/login-url`);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Unable to start Google sign-in: ${text}`);
      }
      const data = await response.json();
      window.location.href = data.auth_url;
    } catch (err) {
      setError(err.message);
      setAuthLoading(false);
    }
  };

  const loadPickerScript = async () => {
    if (window.google && window.google.picker) {
      return;
    }
    return new Promise((resolve, reject) => {
      const existing = document.getElementById('gapi-script');
      if (existing) {
        existing.addEventListener('load', () => resolve());
        existing.addEventListener('error', () => reject(new Error('Could not load Google Picker script')));
        return;
      }
      const script = document.createElement('script');
      script.id = 'gapi-script';
      script.src = 'https://apis.google.com/js/api.js';
      script.onload = () => {
        if (window.gapi) {
          window.gapi.load('picker', { callback: resolve });
        } else {
          reject(new Error('Google API client did not initialize.'));
        }
      };
      script.onerror = () => reject(new Error('Failed to load Google API client script.'));
      document.body.appendChild(script);
    });
  };

  const handleLogout = async () => {
    setError('');
    setAuthLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/logout`, {
        method: 'POST',
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Could not sign out: ${text}`);
      }
      setGoogleSignedIn(false);
      setSelectedSpreadsheetTitle('');
      setResultsSheetUrl('');
      setResultsSheetId('');
      setAvailableTimes([]);
      setAvailableOperations([]);
      setSheetInfoLoaded(false);
      localStorage.removeItem('taxi_grouper_active_sheet_id');
      localStorage.removeItem('taxi_grouper_active_sheet_title');
      setAuthMessage('Signed out successfully.');
    } catch (err) {
      setError(err.message);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleOpenPicker = async () => {
    setError('');
    setPickerLoading(true);
    try {
      if (!GOOGLE_API_KEY) {
        throw new Error('Please configure VITE_GOOGLE_API_KEY in your frontend environment.');
      }
      const tokenResponse = await fetch(`${BACKEND_URL}/api/auth/token`);
      if (!tokenResponse.ok) {
        throw new Error('Google OAuth session is not available. Please sign in with Google first.');
      }
      const tokenData = await tokenResponse.json();
      await loadPickerScript();
      const picker = new window.google.picker.PickerBuilder()
        .addView(new window.google.picker.DocsView(window.google.picker.ViewId.SPREADSHEETS).setIncludeFolders(true))
        .addView(new window.google.picker.DocsUploadView())
        .setOAuthToken(tokenData.access_token)
        .setDeveloperKey(GOOGLE_API_KEY)
        .setCallback((data) => {
          const action = data.action;
          if (action === window.google.picker.Action.PICKED) {
            const doc = data.docs?.[0];
            console.log('Picker selected doc:', doc);
            if (doc?.id) {
              handleSheetSelected(doc.id, doc.name);
            } else {
              setPickerLoading(false);
            }
            return;
          }

          if (
            action === window.google.picker.Action.CANCEL ||
            action === window.google.picker.Action.CLOSE
          ) {
            setPickerLoading(false);
          }
        })
        .build();
      picker.setVisible(true);
    } catch (err) {
      setError(err.message);
      setPickerLoading(false);
    }
  };

  const loadSheetInfo = async (sheetId, sheetName, preserveFilters = false) => {
    setError('');
    setSheetLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/sheet-info`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ sheet_id: sheetId }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Failed to load sheet metadata: ${text}`);
      }
      const payload = await response.json();
      const effectiveSheetId = payload.sheet_id || sheetId;
      setResultsSheetId(effectiveSheetId);
      setSelectedSpreadsheetTitle(sheetName || payload.sheet_title || 'Google Sheet');
      setResultsSheetUrl(payload.sheet_url || `https://docs.google.com/spreadsheets/d/${effectiveSheetId}/edit`);
      setAvailableTimes(payload.available_times ?? []);
      setAvailableOperations(payload.available_operations ?? []);
      setSheetInfoLoaded(true);
      localStorage.setItem('taxi_grouper_active_sheet_id', effectiveSheetId);
      localStorage.setItem('taxi_grouper_active_sheet_title', sheetName || payload.sheet_title || 'Google Sheet');

      if (!preserveFilters) {
        setTimeFilter('all');
        setOperationFilter('all');
      } else {
        if (timeFilter !== 'all' && !payload.available_times?.includes(timeFilter)) {
          setTimeFilter('all');
        }
        if (operationFilter !== 'all' && !payload.available_operations?.includes(operationFilter)) {
          setOperationFilter('all');
        }
      }

      setGroupedData([]);
      setStats(null);
      setWarnings([]);
      setValidation(null);
    } catch (err) {
      setError(err.message);
      setResultsSheetId('');
      setSelectedSpreadsheetTitle('');
      setResultsSheetUrl('');
      setAvailableTimes([]);
      setAvailableOperations([]);
      setSheetInfoLoaded(false);
    } finally {
      setSheetLoading(false);
    }
  };

  const handleSheetSelected = async (sheetId, sheetName) => {
    setPickerLoading(false);
    await loadSheetInfo(sheetId, sheetName, false);
  };

  const handleRunGrouping = async () => {
    if (!resultsSheetId) {
      setError('Pick a Google Sheet before running grouping.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/group-sheet`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sheet_id: resultsSheetId,
          time_filter: timeFilter === 'all' ? null : timeFilter,
          type_course_filter: typeCourseFilter || null,
          operation_filter: operationFilter === 'all' ? null : operationFilter,
          use_ml: true,
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Grouping sheet failed: ${text}`);
      }
      const payload = await response.json();
      setGroupedData(payload.grouped_data ?? []);
      setStats(payload.stats ?? null);
      setWarnings(payload.warnings ?? []);
      setValidation(payload.validation ?? null);
      const newUrl = payload.sheet_url ?? (resultsSheetUrl || `https://docs.google.com/spreadsheets/d/${resultsSheetId}/edit`);
      console.log('[DEBUG] Group response sheet_url:', payload.sheet_url);
      console.log('[DEBUG] Setting resultsSheetUrl to:', newUrl);
      setResultsSheetUrl(newUrl);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleValidateCorrections = async () => {
    if (!resultsSheetId) {
      setError('Pick a Google Sheet before validating corrections.');
      return;
    }
    setError('');
    setValidateMessage('');
    setValidationLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/validate-sheet`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ sheet_id: resultsSheetId }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Validation failed: ${text}`);
      }
      const payload = await response.json();
      setValidation(payload.validation ?? null);
      if (payload.validation?.valid) {
        setValidateMessage('Corrections validated successfully.');
      } else {
        setValidateMessage('Corrections validated. Please review any validation errors.');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setValidationLoading(false);
    }
  };

  const handleRefreshSheet = async () => {
    if (!resultsSheetId) return;
    setError('');
    setRefreshLoading(true);
    try {
      await loadSheetInfo(resultsSheetId, selectedSpreadsheetTitle || 'Google Sheet', true);
      if (groupedData.length || stats) {
        await handleRunGrouping();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshLoading(false);
    }
  };

  const handleFileChange = (event) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const droppedFile = event.dataTransfer.files?.[0];
    if (droppedFile) setFile(droppedFile);
  };

  const handleSubmit = async () => {
    if (!file) {
      setError('Please select an .xlsx file first.');
      return;
    }
    setError('');
    setLoading(true);
    setGroupedData([]);
    setStats(null);
    setWarnings([]);
    setValidation(null);
    setResultsSheetUrl('');

    try {
      const params = new URLSearchParams();
      if (timeFilter) params.append('time_filter', timeFilter);
      if (typeCourseFilter) params.append('type_course_filter', typeCourseFilter);
      if (operationFilter) params.append('operation_filter', operationFilter);
      params.append('use_ml', 'true');

      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`${BACKEND_URL}/api/group?${params.toString()}`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Grouping failed: ${response.status} ${text}`);
      }
      const payload = await response.json();
      setGroupedData(payload.grouped_data ?? []);
      setStats(payload.stats ?? null);
      setWarnings(payload.warnings ?? []);
      setValidation(payload.validation ?? null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!groupedData.length) return;
    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${BACKEND_URL}/api/export`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(groupedData),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Export failed: ${response.status} ${text}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'grouped_output.xlsx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveToDrive = async () => {
    if (!groupedData.length) return;
    setSaveDriveLoading(true);
    setSaveDriveMessage('');
    setSavedDriveUrl('');
    setError('');

    try {
      const response = await fetch(`${BACKEND_URL}/api/save-drive`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ grouped_data: groupedData, sheet_name: 'Taxi Grouper Results' }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Save to Drive failed: ${response.status} ${text}`);
      }
      const payload = await response.json();
      setSavedDriveUrl(payload.sheet_url || '');
      setSaveDriveMessage('Saved results to Drive successfully.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSaveDriveLoading(false);
    }
  };

  return (
    <div className="app-container">
      <header>
        <h1>Taxi Grouper</h1>
        <p>Upload an Excel file, group agents, and export the formatted dispatch plan.</p>
      </header>

      <section className="card upload-card">
        <h2>Upload file</h2>
        <div
          className="dropzone"
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          onDragEnter={(e) => e.preventDefault()}
        >
          <p>Drag & drop an .xlsx file here, or click to browse.</p>
          <input type="file" accept=".xlsx" onChange={handleFileChange} />
          <div className="selected-file">{file ? file.name : 'No file selected'}</div>
        </div>

        <div className="filters-row">
          <label>
            Time filter
            <input value={timeFilter} onChange={(e) => setTimeFilter(e.target.value)} placeholder="07:00" />
          </label>
          <label>
            Course type
            <input value={typeCourseFilter} onChange={(e) => setTypeCourseFilter(e.target.value)} placeholder="Ramassage or Retour" />
          </label>
          <label>
            Operation
            <input value={operationFilter} onChange={(e) => setOperationFilter(e.target.value)} placeholder="Client or operation" />
          </label>
        </div>

        <div className="button-row">
          <button className="button-primary" onClick={handleSubmit} disabled={loading}>
            {loading ? 'Grouping…' : 'Group agents'}
          </button>
          <button className="button-secondary" onClick={handleExport} disabled={loading || !groupedData.length}>
            {loading ? 'Exporting…' : 'Export Excel'}
          </button>
          <button className="button-secondary" onClick={handleSaveToDrive} disabled={saveDriveLoading || !groupedData.length}>
            {saveDriveLoading ? 'Saving…' : 'Save to Drive'}
          </button>
        </div>

        {savedDriveUrl && (
          <div className="alert alert-success">
            {saveDriveMessage} <a href={savedDriveUrl} target="_blank" rel="noreferrer">Open saved sheet ↗</a>
          </div>
        )}

        {error && <div className="alert alert-error">{error}</div>}
      </section>

      <section className="card google-card">
        <h2>Google Sheets integration</h2>
        <p>Sign in with Google, select a spreadsheet, and keep it active as your workspace sheet.</p>
        {!googleSignedIn ? (
          <button className="button-primary" onClick={handleGoogleSignIn} disabled={authLoading}>
            {authLoading ? 'Signing in…' : 'Sign in with Google'}
          </button>
        ) : (
          <>
            <div className="button-row">
              <button className="button-secondary" onClick={handleOpenPicker} disabled={pickerLoading || sheetLoading || loading}>
                {pickerLoading ? 'Opening picker…' : selectedSpreadsheetTitle ? 'Change sheet' : 'Choose spreadsheet'}
              </button>
              <button className="button-secondary" onClick={handleLogout} disabled={authLoading}>
                {authLoading ? 'Signing out…' : 'Sign out'}
              </button>
            </div>
            {selectedSpreadsheetTitle && (
              <p>
                Active sheet: <strong>{selectedSpreadsheetTitle}</strong>
              </p>
            )}
          </>
        )}
        {authMessage && <div className="alert alert-success">{authMessage}</div>}
        {!GOOGLE_API_KEY && (
          <div className="alert alert-warning">
            Missing Google Picker API key. Set <code>VITE_GOOGLE_API_KEY</code> in <code>.env</code>.
          </div>
        )}
      </section>

      {!resultsSheetId ? (
        <section className="card workspace-empty">
          <div className="empty-state-icon">📄</div>
          <h2>Connect a Google Sheet to begin</h2>
          <p>
            Sign in and choose a spreadsheet from your Drive. The sheet stays active for the whole workspace session until you change it.
          </p>
          <button
            className="button-primary"
            onClick={googleSignedIn ? handleOpenPicker : handleGoogleSignIn}
            disabled={authLoading || pickerLoading}
          >
            {googleSignedIn ? 'Pick a spreadsheet' : authLoading ? 'Signing in…' : 'Sign in with Google'}
          </button>
        </section>
      ) : (
        <section className="card workspace-card">
          <div className="workspace-toolbar">
            <div className="workspace-controls">
              <div className="workspace-control-group">
                <div className="control-label">Dispatch type</div>
                <div className="toggle-group">
                  {['Ramassage', 'Retour'].map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={option === typeCourseFilter ? 'button-primary' : 'button-secondary'}
                      onClick={() => setTypeCourseFilter(option)}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              <div className="workspace-control-group">
                <div className="control-label">Location</div>
                <div className="select-shell">
                  <select value={location} onChange={(e) => setLocation(e.target.value)} className="select-field">
                    <option value="Lac 2">Lac 2</option>
                    <option value="Lac 3">Lac 3</option>
                    <option value="Centre Urbain Nord">Centre Urbain Nord</option>
                  </select>
                </div>
              </div>

              <div className="workspace-control-group">
                <div className="control-label">Time</div>
                <div className="select-shell">
                  <select
                    value={timeFilter}
                    onChange={(e) => setTimeFilter(e.target.value)}
                    className="select-field"
                    disabled={!sheetInfoLoaded || availableTimes.length === 0}
                  >
                    {!sheetInfoLoaded ? (
                      <option>Load a sheet first</option>
                    ) : (
                      <>
                        <option value="all">All times</option>
                        {availableTimes.map((time) => (
                          <option key={time} value={time}>{time}</option>
                        ))}
                      </>
                    )}
                  </select>
                </div>
              </div>
            </div>

            <button className="button-primary" onClick={handleRunGrouping} disabled={loading || sheetLoading}>
              {loading ? 'Running…' : 'Run grouping'}
            </button>
          </div>

          <div className="workspace-more-toggle">
            <button className="button-secondary" type="button" onClick={() => setShowMoreFilters(!showMoreFilters)}>
              {showMoreFilters ? 'Hide filters' : 'More filters'}
            </button>
          </div>

          {showMoreFilters && (
            <div className="workspace-more-filters">
              <div className="workspace-control-group full-width">
                <div className="control-label">Client / operation</div>
                <div className="select-shell">
                  <select
                    value={operationFilter}
                    onChange={(e) => setOperationFilter(e.target.value)}
                    className="select-field"
                    disabled={!sheetInfoLoaded || availableOperations.length === 0}
                  >
                    {!sheetInfoLoaded ? (
                      <option>Load a sheet first</option>
                    ) : (
                      <>
                        <option value="all">All</option>
                        {availableOperations.map((operation) => (
                          <option key={operation} value={operation}>{operation}</option>
                        ))}
                      </>
                    )}
                  </select>
                </div>
                <div className="helper-text">Only include agents from this client/operation.</div>
              </div>
            </div>
          )}

          <div className="sheet-panel-header">
            <div>
              <h2>{selectedSpreadsheetTitle || 'Live Google Sheet'}</h2>
              <p className="sheet-panel-subtitle">
                Embedded Google Sheet. Inline editing depends on your browser's active Google login; if you are not signed in, the frame will prompt you.
              </p>
            </div>
            <div className="sheet-panel-actions">
              <button className="button-secondary" onClick={handleRefreshSheet} disabled={refreshLoading || loading || sheetLoading}>
                {refreshLoading ? 'Refreshing…' : 'Refresh'}
              </button>
              <button
                className="button-secondary"
                onClick={handleValidateCorrections}
                disabled={validationLoading || loading || sheetLoading || !resultsSheetId}
              >
                {validationLoading ? 'Validating…' : 'Validate Corrections'}
              </button>
              {sheetOpenUrl && (
                <a className="sheet-open-link" href={sheetOpenUrl} target="_blank" rel="noreferrer">
                  Open in new tab ↗
                </a>
              )}
            </div>
          </div>
          {validateMessage && (
            <div className="alert alert-success">
              {validateMessage}
            </div>
          )}
          <div className="sheet-embed-frame-shell">
            <iframe
              className="sheet-embed-frame"
              title="Google Sheets embed"
              src={sheetEmbedUrl}
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              allowFullScreen
            />
          </div>
        </section>
      )}

      {stats && (
        <section className="card stats-card">
          <h2>Results</h2>
          <div className="stats-grid">
            <div className="stat-card">
              <label>Total agents</label>
              <div className="stat-value">{stats.total_agents}</div>
            </div>
            <div className="stat-card">
              <label>Total taxis</label>
              <div className="stat-value">{stats.total_taxis}</div>
            </div>
            <div className="stat-card">
              <label>Unknown addresses</label>
              <div className="stat-value">{stats.unknown_count}</div>
            </div>
          </div>
          {warnings.length > 0 && (
            <div className="alert alert-warning">
              <strong>Warnings:</strong>
              <ul>{warnings.map((warning, idx) => <li key={idx}>{warning}</li>)}</ul>
            </div>
          )}
          {validation && (
            <div className={`alert ${validation.valid ? 'alert-success' : 'alert-error'}`}>
              <strong>Validation:</strong> {validation.valid ? 'Valid' : 'Invalid'}
              {validation.errors?.length > 0 && (
                <div>
                  <strong>Errors:</strong>
                  <ul>{validation.errors.map((err, idx) => <li key={idx}>{err}</li>)}</ul>
                </div>
              )}
              {validation.taxi_reports?.length > 0 && (
                <details>
                  <summary>Per-taxi validation report</summary>
                  <div className="report-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Taxi</th>
                          <th>Agents</th>
                          <th>Zones</th>
                          <th>Status</th>
                          <th>Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {validation.taxi_reports.map((row, idx) => (
                          <tr key={idx}>
                            <td>{row.Taxi}</td>
                            <td>{row['Agents count']}</td>
                            <td>{row['Zones inside taxi']}</td>
                            <td>{row['Validation status']}</td>
                            <td>{row['Error message'] || row['Group reason'] || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </div>
          )}
        </section>
      )}

      {groupedData.length > 0 && (
        <section className="card table-card">
          <h2>Grouped agents</h2>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Taxi</th>
                  <th>Name</th>
                  <th>Address</th>
                  <th>Detected destination</th>
                  <th>Zone</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(groupedByTaxi).map(([taxi, rows]) => (
                  <>
                    {rows.map((row, rowIndex) => (
                      <tr
                        key={`${taxi}-${rowIndex}`}
                        style={{ backgroundColor: getTaxiColor(taxi) }}
                      >
                        <td>{taxi}</td>
                        <td>{row['Nom - Prénom'] || row['Nom - Prenom'] || row['Nom'] || '—'}</td>
                        <td>{row['Adresse'] || row['Destination'] || row['CleanAddress'] || '—'}</td>
                        <td>{row['DetectedDestination'] || '—'}</td>
                        <td>{row['DestinationZone'] || row['Zone'] || '—'}</td>
                      </tr>
                    ))}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

export default App;
