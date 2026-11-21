import { registerStrings } from './index';
import { enMore } from './more.en';
import { urMore } from './more.ur';

// Imported for its side effect by the lazy citizen chunks only.
registerStrings(enMore, urMore);
