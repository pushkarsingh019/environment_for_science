export interface NoticesProps {
  error: string | null;
  status: string | null;
}

/** Request failures (`role="alert"`) and the demo reset notice (`role="status"`). */
export function Notices(props: NoticesProps): JSX.Element | null {
  const { error, status } = props;
  if (error === null && status === null) return null;

  return (
    <>
      {error && (
        <div className="notice notice--error" role="alert">
          <strong>Request failed.</strong> {error}
        </div>
      )}
      {status && (
        <div className="notice notice--status" data-testid="demo-reset-notice" role="status">
          {status}
        </div>
      )}
    </>
  );
}
