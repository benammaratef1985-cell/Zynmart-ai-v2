#!/data/data/com.termux/files/usr/bin/bash
# publish.sh - سكربت نشر سريع لـ AI for
# الاستخدام: ./publish.sh "وصف التعديل"

cd ~/Zynmart-ai-v2 || { echo "❌ المجلد غير موجود"; exit 1; }

echo "🔍 فحص syntax..."
python -c "import ast; ast.parse(open('main.py',encoding='utf-8').read())" || { echo "❌ خطأ syntax — لم يتم الرفع"; exit 1; }
echo "✅ syntax سليم"

MSG="${1:-update: auto publish $(date +%Y-%m-%d_%H:%M)}"

echo "📦 commit + push..."
git add main.py
git commit -m "$MSG" || { echo "ℹ️ لا يوجد تغيير جديد"; exit 0; }
git push

echo ""
echo "✅ تم الرفع بنجاح!"
echo "🌐 Render سيُعيد النشر تلقائيًا خلال دقيقتين."
echo "🔗 راقب: https://dashboard.render.com"
