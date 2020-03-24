del .aws\credentials

for /f %%A IN (aws.txt) DO (
  .\Downloads\oktaws.exe wex-%%A /U yegor.gorshkov@wexinc.com /p "<<REMOVED>>" /A %%A
)
