#!/usr/bin/env python3
"""Install the free Argos English-to-Chinese model for local inference."""

import argostranslate.package
import argostranslate.translate


def main() -> None:
    installed = argostranslate.translate.get_installed_languages()
    english = next((language for language in installed if language.code == "en"), None)
    chinese = next((language for language in installed if language.code == "zh"), None)
    if english and chinese:
        try:
            english.get_translation(chinese)
            print("Argos English-to-Chinese model is already installed.")
            return
        except Exception:
            pass

    argostranslate.package.update_package_index()
    packages = argostranslate.package.get_available_packages()
    package = next(
        (candidate for candidate in packages if candidate.from_code == "en" and candidate.to_code == "zh"),
        None,
    )
    if package is None:
        raise RuntimeError("Argos package index has no English-to-Chinese model")
    argostranslate.package.install_from_path(package.download())
    print(f"Installed Argos English-to-Chinese model {package.package_version}.")


if __name__ == "__main__":
    main()
