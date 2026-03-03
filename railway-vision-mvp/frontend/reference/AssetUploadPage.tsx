import { ChangeEvent, FormEvent, useState } from "react";
import styles from "./AssetUploadPage.module.css";

type UploadResult = {
  id: string;
};

type AssetUploadPageProps = {
  onUpload: (file: File, sensitivity: string) => Promise<UploadResult>;
  onCreateTask?: (assetId: string) => void;
};

export function AssetUploadPage({
  onUpload,
  onCreateTask,
}: AssetUploadPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [sensitivity, setSensitivity] = useState("L2");
  const [assetId, setAssetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
    setAssetId(null);
    setError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const result = await onUpload(file, sensitivity);
      setAssetId(result.id);
    } catch (uploadError) {
      const message =
        uploadError instanceof Error ? uploadError.message : "上传失败，请重试。";
      setAssetId(null);
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className={styles.page}>
      <section className={styles.container}>
        <header className={styles.header}>
          <h1 className={styles.title}>资产上传</h1>
          <p className={styles.description}>
            上传业务资产并完成入库，成功后再进入任务创建。
          </p>
        </header>

        <form className={styles.card} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="assetFile">
              选择文件
            </label>
            <input
              className={styles.input}
              id="assetFile"
              type="file"
              onChange={handleFileChange}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="sensitivity">
              敏感级别
            </label>
            <select
              className={styles.select}
              id="sensitivity"
              value={sensitivity}
              onChange={(event) => setSensitivity(event.target.value)}
            >
              <option value="L1">L1</option>
              <option value="L2">L2</option>
              <option value="L3">L3</option>
            </select>
          </div>

          <button
            className={styles.primaryButton}
            type="submit"
            disabled={!file || submitting}
          >
            {submitting ? "上传中" : "上传资产"}
          </button>
        </form>

        {(assetId || error) && (
          <section className={styles.card} aria-live="polite">
            {error ? (
              <div className={styles.feedback}>{error}</div>
            ) : (
              <>
                <div className={styles.assetMeta}>
                  <span className={styles.metaLabel}>资产ID</span>
                  <code className={styles.metaValue}>{assetId}</code>
                </div>
                {assetId && onCreateTask ? (
                  <button
                    className={styles.primaryButton}
                    type="button"
                    onClick={() => onCreateTask(assetId)}
                  >
                    去创建任务
                  </button>
                ) : null}
              </>
            )}
          </section>
        )}
      </section>
    </main>
  );
}

export default AssetUploadPage;
