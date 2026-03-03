# 模型包规范（railway-vision-mvp）

## 1. 固定目录结构

```text
model_package.zip
  ├── manifest.json
  ├── model.enc
  ├── signature.sig
  └── README.txt
```

- `manifest.json`: 模型指纹与元数据（`model_id`、`version`、`model_hash` 等）
- `model.enc`: 加密后的模型权重（支持 onnx/pt 的加密字节）
- `signature.sig`: 对 `manifest.json + model.enc` 的 RSA-SHA256 签名
- `README.txt`: 说明文件

## 2. 验签与校验规则

中心端 `/models/register` 会严格执行：

1. ZIP 结构完整性校验（四个固定文件必须齐全）
2. 解析 `manifest.json`
3. 计算 `sha256(model.enc)`，与 `manifest.model_hash` 比对
4. 使用我方公钥验签 `signature.sig`
5. 校验通过后入库并仅保存加密态 `model.enc`

边缘端 `/edge/pull_model` + Agent 会执行：

1. 拉取 `manifest + model.enc + signature`
2. 本地公钥验签
3. 哈希校验
4. 使用我方控制的解密密钥解密至临时目录
5. 推理结果附带 `model_id/model_hash`

## 3. manifest 示例

```json
{
  "schema_version": "1.0",
  "model_id": "car_number_ocr",
  "version": "v1.0.0",
  "model_hash": "<sha256_of_model.enc>",
  "task_type": "car_number_ocr",
  "input_schema": "image|video",
  "output_schema": "json:bbox,text,confidence",
  "published_at": "2026-02-27T01:02:03Z",
  "publisher": "railway-platform"
}
```

## 4. 打包工具（我方）

后端提供 CLI：

```bash
python -m app.services.model_package_tool \
  --model-path /tmp/demo_model.onnx \
  --model-id car_number_ocr \
  --version v1.0.0 \
  --encrypt-key /app/keys/model_encrypt.key \
  --signing-private-key /app/keys/model_sign_private.pem \
  --output /tmp/model_package.zip
```

该工具会完成：

- 模型加密（Fernet）
- `model_hash` 计算
- RSA 签名
- 标准 ZIP 组包
