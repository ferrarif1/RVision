# Required Keys For Remote Training Worker

将独立训练 worker 下发到远端机器前，需要把以下文件放到同目录 `keys/` 下：

- `model_decrypt.key`：用于解密控制面下发的基线模型包
- `model_encrypt.key`：用于加密候选模型包中的 `model.enc`
- `model_sign_private.pem`：用于对候选模型包签名

仓库内默认来源：

- `edge/keys/model_decrypt.key`
- `docker/keys/model_encrypt.key`
- `docker/keys/model_sign_private.pem`

不要把真实密钥提交回仓库。
