# PaddleOCR配置

优先推荐本地模式，使材料不离开用户设备。官方安装文档：[PaddleOCR Installation](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/installation.html)。

## 本地安装

根据官方文档安装与硬件匹配的PaddlePaddle，再安装：

```bash
python3 -m pip install paddleocr
```

将 `providers.paddle_ocr.enabled` 改为 `true`，`mode` 保持 `local`。

## 用户自选云端模式

只有用户明确选择云端OCR时才配置：

```text
PADDLE_OCR_API_KEY=用户自己的云端凭据
```

界面必须提示文件将上传到第三方服务。该凭据只配置在用户本地Agent，不配置到项目申报助手网站。

## 验证

1. 识别一张不含敏感内容的中英文测试图。
2. 识别扫描PDF第一页。
3. 检查文本、置信度、表格或版面输出。
4. 本地模式断网后重复测试。

## 降级

PaddleOCR不可用时使用宿主平台OCR；仍不可用时要求用户提供可复制文本。网站检测到纯扫描件时只标记“需本地OCR”。

## 清理

云端模式删除密钥；本地模式可卸载Python包和模型缓存。客户输入与OCR输出不得放进技能目录。
